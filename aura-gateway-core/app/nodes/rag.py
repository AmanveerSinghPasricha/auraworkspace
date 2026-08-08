"""
Aura Gateway Core - Production Vectorless RAG Engine
===================================================
Layout-aware, structure-first RAG engine using Docling layout parsing via External API,
LiteLLM Gateway integration, generalized BM25 + Tree search, layered multi-pass routing,
and immutable filesystem caching. Integrated with LangGraph state.
"""

import os
import sys
import json
import uuid
import logging
import hashlib
import asyncio
import math
import re
from collections import Counter
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from pydantic import BaseModel, Field

# Raise recursion limit for deep document structures
sys.setrecursionlimit(5000)

# Gateway Interoperability SDK (LiteLLM + Instructor)
import instructor
from litellm import acompletion
from litellm.exceptions import RateLimitError

# LangGraph Core Integrations & Centralized Settings
from langchain_core.messages import AIMessage
from app.config import settings
from app.state import GraphState
from app.services.docling_client import parse_pdf_via_api

logger = logging.getLogger("vectorless_rag")

os.environ["MALLOC_TRIM_THRESHOLD_"] = "65536"
os.environ["OMP_NUM_THREADS"] = "1"

instructor_client = instructor.from_litellm(acompletion)

# Global singleton for lazy-loading VectorlessEngine
_vectorless_engine_instance: Optional["VectorlessEngine"] = None


def get_vectorless_engine() -> "VectorlessEngine":
    """Lazy-loads Vectorless Engine instance on first execution to keep app boot memory minimal."""
    global _vectorless_engine_instance
    if _vectorless_engine_instance is None:
        _vectorless_engine_instance = VectorlessEngine()
    return _vectorless_engine_instance


# =====================================================================
# 1. DOMAIN SCHEMAS & DATA STRUCTURES
# =====================================================================
class TreeNode(BaseModel):
    node_id: str = Field(default_factory=lambda: f"node_{uuid.uuid4().hex[:8]}")
    parent_id: Optional[str] = None
    title: str
    level: int  # 0: Root, 1: Chapter/H1, 2: Section/H2, 3: Sub-section/Paragraph
    page_numbers: List[int] = Field(default_factory=list)
    content_blocks: List[str] = Field(default_factory=list)
    summary: Optional[str] = None
    children: List["TreeNode"] = Field(default_factory=list)

    def full_content(self) -> str:
        """Iteratively extracts unchunked text and tables for this node and all child nodes."""
        text_blocks = ["\n".join(self.content_blocks)]
        stack = list(reversed(self.children))

        while stack:
            curr = stack.pop()
            if curr.content_blocks:
                text_blocks.append("\n".join(curr.content_blocks))
            if curr.children:
                stack.extend(reversed(curr.children))

        return "\n\n".join(filter(None, text_blocks)).strip()


class IntentAndRoutingOutput(BaseModel):
    reasoning: str = Field(description="Step-by-step logic behind intent evaluation and section selection")
    is_global_query: bool = Field(description="True if query asks for an overall summary, high-level overview, or main themes across the file")
    target_node_ids: List[str] = Field(default_factory=list, description="List of section node_ids to retrieve for point-based lookups")


# =====================================================================
# 2. VECTORLESS ENGINE & PARSER SERVICE
# =====================================================================
class VectorlessEngine:
    def __init__(self, cache_dir: str = ".vectorless_cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def compute_file_hash(self, file_path: str) -> str:
        """Computes SHA-256 fingerprint for immutable document caching."""
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
        return hasher.hexdigest()

    def _build_tree_from_docling_dict(self, doc_dict: dict, root_title: str) -> TreeNode:
        """Constructs a properly nested TreeNode hierarchy from raw Docling JSON schema using a level stack."""
        root = TreeNode(title=root_title, level=0)

        texts = doc_dict.get("texts", [])
        tables = doc_dict.get("tables", [])

        if not texts and not tables:
            root.content_blocks.append(json.dumps(doc_dict, indent=2))
            return root

        node_stack: List[Tuple[int, TreeNode]] = [(0, root)]

        for text_item in texts:
            label = text_item.get("label", "text")
            content = text_item.get("text", "").strip()
            prov = text_item.get("prov", [])
            page_no = prov[0].get("page_no", 1) if prov else 1

            if not content:
                continue

            if "header" in label or "title" in label:
                level = 1 if "title" in label else 2

                # Pop deeper nodes until we locate parent level
                while node_stack and node_stack[-1][0] >= level:
                    node_stack.pop()

                parent_node = node_stack[-1][1] if node_stack else root

                new_node = TreeNode(
                    title=content,
                    level=level,
                    page_numbers=[page_no],
                    parent_id=parent_node.node_id
                )
                parent_node.children.append(new_node)
                node_stack.append((level, new_node))
            else:
                target_node = node_stack[-1][1]
                target_node.content_blocks.append(content)
                if page_no not in target_node.page_numbers:
                    target_node.page_numbers.append(page_no)

        for tbl in tables:
            tbl_md = tbl.get("text", "")
            if tbl_md:
                node_stack[-1][1].content_blocks.append(f"[TABLE]\n{tbl_md}")

        return root

    async def parse_file_to_tree(self, file_path: str) -> TreeNode:
        """Delegates document parsing to Docling microservice and builds TreeNode hierarchy."""
        logger.info(f"📖 [PARSING API] Sending file to remote Docling service: {file_path}")
        root_title = Path(file_path).name

        parsed_response = await parse_pdf_via_api(file_path)
        doc_json = parsed_response.get("json") or parsed_response
        return self._build_tree_from_docling_dict(doc_json, root_title)

    async def generate_node_summaries(self, root_node: TreeNode):
        """
        PROGRESSIVE LAZY SUMMARIZATION + STRUCTURAL PRUNING:
        - Summarizes ONLY top-level parent chapters (level <= 1).
        - Assigns instant deterministic previews for inner child nodes (0 API overhead).
        """
        all_nodes: List[TreeNode] = []
        queue = [root_node]

        while queue:
            curr = queue.pop(0)
            all_nodes.append(curr)
            for child in curr.children:
                child.parent_id = curr.node_id
                queue.append(child)

        top_level_nodes = [
            n for n in all_nodes
            if n.level <= 1 and len(n.full_content().split()) >= 15
        ]

        logger.info(
            f"🚀 [LAZY INDEXING] Summarizing {len(top_level_nodes)} main chapters via LLM API "
            f"(Skipping {len(all_nodes) - len(top_level_nodes)} inner nodes/boilerplate)..."
        )

        for n in all_nodes:
            if n not in top_level_nodes:
                raw = n.full_content().strip()
                preview = raw[:120].replace("\n", " ") if raw else f"Section content under {n.title}"
                n.summary = f"[{n.title}] {preview}..."

        semaphore = asyncio.Semaphore(1)

        async def summarize_parent_node(index: int, node: TreeNode):
            raw_text = node.full_content()
            async with semaphore:
                await asyncio.sleep(1.0)
                logger.info(f" Summarizing Chapter [{index + 1}/{len(top_level_nodes)}]: '{node.title}'...")

                models_to_try = [settings.LLM_RAG_PRIMARY, settings.LLM_RAG_FALLBACK]

                for target_model in models_to_try:
                    try:
                        response = await acompletion(
                            model=target_model,
                            messages=[
                                {"role": "system", "content": "Summarize key info in 1-2 clear sentences."},
                                {"role": "user", "content": f"Chapter: {node.title}\nContent:\n{raw_text[:1200]}"}
                            ],
                            max_tokens=75,
                            temperature=0.0,
                            num_retries=1,
                        )
                        node.summary = response.choices[0].message.content.strip()
                        logger.info(f"  ✅ [{target_model}] Summarized '{node.title}'")
                        return
                    except RateLimitError:
                        logger.warning(f"  ⏳ Rate limit on '{target_model}' for '{node.title}'. Waiting 2s...")
                        await asyncio.sleep(2.0)
                    except Exception as e:
                        logger.warning(f"  ⚠️ Attempt failed on '{target_model}' for '{node.title}': {e}")

                node.summary = f"Section text content under {node.title}"

        for idx, n in enumerate(top_level_nodes):
            await summarize_parent_node(idx, n)

        logger.info("✅ [LAZY INDEXING] Document skeleton indexed successfully!")

    def save_tree_to_cache(self, file_hash: str, root_node: TreeNode):
        """Stores structured JSON tree to local disk cache."""
        cache_file = self.cache_dir / f"{file_hash}.json"
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(root_node.model_dump(), f, indent=2)
        logger.info(f"💾 [CACHE] Tree saved at: {cache_file}")

    def load_tree_from_cache(self, file_hash: str) -> Optional[TreeNode]:
        """Loads cached tree if SHA-256 fingerprint matches."""
        cache_file = self.cache_dir / f"{file_hash}.json"
        if cache_file.exists():
            logger.info(f"⚡ [CACHE HIT] Loaded pre-parsed tree for hash: {file_hash[:12]}")
            with open(cache_file, "r", encoding="utf-8") as f:
                return TreeNode(**json.load(f))
        return None

    def get_lightweight_index(self, node: TreeNode, max_depth: Optional[int] = None, current_depth: int = 0) -> Dict[str, Any]:
        """Strips heavy raw content and truncates summaries to keep routing prompts compact."""
        summary_text = (node.summary or "")[:100]
        item = {
            "node_id": node.node_id,
            "title": node.title[:80],
            "pages": node.page_numbers[:3],
            "summary": summary_text,
        }
        if max_depth is None or current_depth < max_depth:
            item["children"] = [
                self.get_lightweight_index(c, max_depth, current_depth + 1)
                for c in node.children[:20]  # Cap child branch expansion
            ]
        return item


# =====================================================================
# 3. LAYERED GENERALIZED HYBRID ROUTER LOGIC
# =====================================================================
class VectorlessRouter:
    def __init__(self, engine: VectorlessEngine):
        self.engine = engine

    def _flatten_tree_index(self, node: TreeNode) -> List[Dict[str, Any]]:
        """Flatten tree nodes into an indexed search pool with ancestor paths."""
        flat_list = []
        queue = [(node, [])]

        while queue:
            curr, path = queue.pop(0)
            current_path = path + [curr.title]

            flat_list.append({
                "node_id": curr.node_id,
                "title": curr.title,
                "summary": curr.summary or "",
                "path": " > ".join(current_path),
                "word_count": len(curr.full_content().split()),
                "node_ref": curr
            })

            for child in curr.children:
                queue.append((child, current_path))

        return flat_list

    async def route(self, query: str, root_tree: TreeNode) -> Tuple[bool, List[str], Any]:
        """
        GENERALIZED HYBRID ROUTER:
        - Works for ANY document schema (NIST, ISO, SEC Filings, Standard Manuals).
        - Zero hardcoded regex, zero hardcoded section codes.
        - Uses BM25/IDF score ranking over structural node titles & summaries.
        """
        all_candidates = self._flatten_tree_index(root_tree)
        if not all_candidates:
            return False, [root_tree.node_id], None

        content_nodes = [c for c in all_candidates if c["word_count"] >= 10]
        if not content_nodes:
            content_nodes = all_candidates

        query_tokens = [t.lower() for t in re.findall(r'\b\w+\b', query) if len(t) > 1]
        doc_count = len(content_nodes)

        idf = {}
        for token in query_tokens:
            n_containing = sum(1 for c in content_nodes if token in (c["title"] + " " + c["summary"]).lower())
            idf[token] = math.log((doc_count - n_containing + 0.5) / (n_containing + 0.5) + 1.0)

        avg_len = sum(len((c["title"] + " " + c["summary"]).split()) for c in content_nodes) / max(doc_count, 1)
        k1, b = 1.5, 0.75

        scored_nodes = []
        for candidate in content_nodes:
            text = f"{candidate['path']} {candidate['summary']}".lower()
            tokens = re.findall(r'\b\w+\b', text)
            doc_len = len(tokens)
            term_freqs = Counter(tokens)

            score = 0.0
            for token in query_tokens:
                if token in term_freqs:
                    tf = term_freqs[token]
                    numerator = idf[token] * tf * (k1 + 1)
                    denominator = tf + k1 * (1 - b + b * (doc_len / max(avg_len, 1)))
                    score += numerator / denominator

            scored_nodes.append((score, candidate))

        scored_nodes.sort(key=lambda x: x[0], reverse=True)
        top_pruned_candidates = [item[1]["node_ref"] for item in scored_nodes[:20]]

        pruned_index = [self.engine.get_lightweight_index(c, max_depth=0) for c in top_pruned_candidates]

        pass1_prompt = f"""You are an enterprise document routing agent.
Analyze the user query against the candidate document sections.

Task:
1. Determine if this is a GLOBAL query (asking for an overall overview/summary of the entire file) or a POINT lookup.
2. If POINT query, select up to 3 relevant node_ids that contain the exact answer.

Candidate Document Sections:
{json.dumps(pruned_index, indent=2)}

User Query: {query}"""

        p1_data, pass1_raw = await instructor_client.chat.completions.create_with_completion(
            model=settings.LLM_RAG_PRIMARY,
            messages=[{"role": "user", "content": pass1_prompt}],
            response_model=IntentAndRoutingOutput,
            temperature=0.0,
            fallbacks=[settings.LLM_RAG_FALLBACK],
            max_retries=2,
        )

        if p1_data.is_global_query:
            logger.info("🌐 [GENERAL ROUTER] Global query intent detected -> Root summary path.")
            return True, [root_tree.node_id], getattr(pass1_raw, "usage", None)

        target_node_ids = p1_data.target_node_ids
        if not target_node_ids and top_pruned_candidates:
            target_node_ids = [top_pruned_candidates[0].node_id]

        logger.info(f"🎯 [GENERAL ROUTER] Selected Target Node IDs: {target_node_ids}")
        return False, target_node_ids, getattr(pass1_raw, "usage", None)


# =====================================================================
# 4. CONTENT FETCHING & SERVICE WORKFLOW
# =====================================================================
def fetch_node_content(node: TreeNode, target_ids: List[str]) -> List[str]:
    """Retrieves full text and tables recursively from target node IDs and child branches."""
    extracted = []
    queue = [node]

    while queue:
        curr = queue.pop(0)
        if curr.node_id in target_ids:
            extracted.append(f"### {curr.title} (Pages: {curr.page_numbers})\n{curr.full_content()}")
        if curr.children:
            queue.extend(curr.children)

    return extracted


async def answer_vectorless_query(query: str, file_path: str, engine: VectorlessEngine) -> Dict[str, Any]:
    """End-to-end processing function for an incoming query and file path."""
    file_hash = engine.compute_file_hash(file_path)

    root_tree = engine.load_tree_from_cache(file_hash)
    if not root_tree:
        root_tree = await engine.parse_file_to_tree(file_path)
        await engine.generate_node_summaries(root_tree)
        engine.save_tree_to_cache(file_hash, root_tree)

    router = VectorlessRouter(engine)
    is_global, target_ids, route_usage = await router.route(query, root_tree)

    if is_global:
        context_str = f"Document Summary: {root_tree.summary}\n\nChapter Overview:\n" + "\n".join([
            f"- {c.title}: {c.summary}" for c in root_tree.children[:30]
        ])
    else:
        context_blocks = fetch_node_content(root_tree, target_ids)
        context_str = "\n\n".join(context_blocks)

    system_instruction = (
        "You are a strict compliance and enterprise document analysis assistant.\n"
        "Answer the user's question grounded EXCLUSIVELY in the provided document context.\n\n"
        "STRICT MANDATORY FORMATTING RULES:\n"
        "1. DO NOT generate Python code, classes, snippets, or pseudo-code under any circumstances.\n"
        "2. DO NOT fabricate time limits (e.g., '30 days') or obligations not explicitly present in the context.\n"
        "3. Provide precise, factual extractions directly matching the document text.\n"
        "4. Include inline citations with section names and page numbers (e.g., [Section AC-2, Page 47])."
    )

    user_payload = f"Context:\n{context_str[:12000]}\n\nQuestion: {query}"

    response = await acompletion(
        model=settings.LLM_RAG_PRIMARY,
        messages=[
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": user_payload}
        ],
        temperature=0.0,
        caching=False,
        fallbacks=[settings.LLM_RAG_FALLBACK],
        num_retries=2,
    )

    extracted_answer = "No response content generated."
    if response and hasattr(response, "choices") and response.choices:
        extracted_answer = response.choices[0].message.content

    return {
        "answer": extracted_answer,
        "is_global": is_global,
        "selected_nodes": target_ids,
        "file_hash": file_hash,
        "usage": getattr(response, "usage", None)
    }


# =====================================================================
# 5. LANGGRAPH NODE EXECUTION WRAPPER
# =====================================================================
async def rag_node(state: GraphState) -> Dict[str, Any]:
    """LangGraph execution node for the Vectorless RAG Engine with Smart Multi-Document Resolver."""
    logger.info("📚 [RAG NODE] Processing query via Vectorless RAG Engine...")

    engine = get_vectorless_engine()
    staged_payload = state.get("staged_action_payload") if isinstance(state, dict) else getattr(state, "staged_action_payload", {})
    messages = state.get("messages", []) if isinstance(state, dict) else getattr(state, "messages", [])
    router_state = state.get("router_state") if isinstance(state, dict) else getattr(state, "router_state", None)

    resolved_query = staged_payload.get("resolved_query") if staged_payload else None
    if not resolved_query and messages:
        raw_msg = messages[-1].content
        resolved_query = raw_msg if isinstance(raw_msg, str) else str(raw_msg)

    doc_path = None

    if staged_payload and staged_payload.get("document_ref"):
        doc_path = staged_payload.get("document_ref")

    if not doc_path and router_state:
        doc_path = getattr(router_state, "last_document_ref", None)

    upload_dir = Path("./uploads")
    if not doc_path or not os.path.exists(doc_path):
        if upload_dir.exists():
            all_uploads = list(upload_dir.glob("*"))
            if all_uploads:
                query_lower = (resolved_query or "").lower()
                for file_entry in all_uploads:
                    clean_name = file_entry.name.lower()
                    base_name = clean_name.split("_", 1)[-1] if "_" in clean_name else clean_name

                    if base_name in query_lower or clean_name in query_lower:
                        doc_path = str(file_entry)
                        logger.info(f"🎯 [RAG RESOLVER] Matched file from prompt intent: {file_entry.name}")
                        break

                if not doc_path and len(all_uploads) == 1:
                    doc_path = str(all_uploads[0])
                    logger.info(f"📌 [RAG RESOLVER] Auto-bound single available document: {doc_path}")

    if not doc_path or not os.path.exists(doc_path):
        if upload_dir.exists() and len(list(upload_dir.glob("*"))) > 1:
            available_files = [f.name.split("_", 1)[-1] for f in upload_dir.glob("*")]
            file_list_str = "\n".join([f"- {name}" for name in available_files])

            return {
                "messages": [AIMessage(
                    content=f"You have multiple documents uploaded. Please specify which document you'd like to query:\n\n{file_list_str}"
                )],
                "validation_errors": ["Ambiguous document target in multi-file workspace."]
            }

        return {
            "messages": [AIMessage(content="Please upload a valid document first to proceed with document-grounded Q&A.")],
            "validation_errors": [f"Document path '{doc_path}' not found or inaccessible."]
        }

    try:
        result = await answer_vectorless_query(
            query=resolved_query,
            file_path=doc_path,
            engine=engine
        )

        finops_ledger = state.get("finops_ledger") if isinstance(state, dict) else getattr(state, "finops_ledger", None)
        new_finops_ledger = finops_ledger.model_copy(deep=True) if finops_ledger and hasattr(finops_ledger, "model_copy") else None

        if new_finops_ledger and result.get("usage"):
            usage = result["usage"]
            prompt_details = getattr(usage, "prompt_tokens_details", None)
            cached_tokens = 0

            if isinstance(prompt_details, dict):
                cached_tokens = prompt_details.get("cached_tokens", 0)
            elif prompt_details is not None:
                cached_tokens = getattr(prompt_details, "cached_tokens", 0)

            try:
                new_finops_ledger.log_transaction_usage(
                    model_response_metadata={
                        "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                        "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
                        "cache_read_tokens": cached_tokens or 0,
                    },
                    model_pricing_rates={"in": 0.00000015, "cached": 0.000000075, "out": 0.0000006},
                )
            except Exception as ledger_err:
                logger.warning(f"⚠️ [FINOPS LEDGER] Non-fatal ledger logging issue: {ledger_err}")

        res = {
            "messages": [AIMessage(content=result["answer"])],
            "validation_errors": []
        }
        if new_finops_ledger:
            res["finops_ledger"] = new_finops_ledger
        return res

    except Exception as exc:
        logger.error(f"❌ [RAG NODE ERROR] Vectorless query failed: {exc}", exc_info=True)
        return {
            "messages": [AIMessage(content="I encountered an issue analyzing the document structure across primary and fallback inference endpoints.")],
            "validation_errors": [str(exc)]
        }