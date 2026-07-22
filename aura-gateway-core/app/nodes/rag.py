"""
Aura Gateway Core - Production Vectorless RAG Engine
===================================================
Layout-aware, structure-first RAG engine using Docling layout parsing,
Async OpenAI, dual-tree index navigation, layered multi-pass routing,
and immutable filesystem caching. Integrated with LangGraph state.
"""

import os
import json
import uuid
import logging
import hashlib
import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from pydantic import BaseModel, Field

# Layout Parsing Engine
from docling.document_converter import DocumentConverter
from docling_core.types.doc import DocItemLabel

# Async OpenAI SDK
from openai import AsyncOpenAI

# LangGraph Core Integrations
from langchain_core.messages import AIMessage
from app.state import GraphState

logger = logging.getLogger("vectorless_rag")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


# =====================================================================
# 1. DOMAIN SCHEMAS & DATA STRUCTURES
# =====================================================================
class TreeNode(BaseModel):
    node_id: str = Field(default_factory=lambda: f"node_{uuid.uuid4().hex[:8]}")
    title: str
    level: int  # 0: Root, 1: H1/Sheet, 2: H2, 3: H3
    page_numbers: List[int] = Field(default_factory=list)
    content_blocks: List[str] = Field(default_factory=list)
    summary: Optional[str] = None
    children: List["TreeNode"] = Field(default_factory=list)

    def full_content(self) -> str:
        """Recursively extracts unchunked text and tables for this node and children."""
        text = "\n".join(self.content_blocks)
        for child in self.children:
            text += f"\n\n{child.full_content()}"
        return text.strip()


class IntentAndRoutingOutput(BaseModel):
    reasoning: str = Field(description="Step-by-step logic behind intent evaluation and section selection")
    is_global_query: bool = Field(description="True if query asks for an overall summary, high-level overview, or main themes across the file")
    target_node_ids: List[str] = Field(default_factory=list, description="List of section node_ids to retrieve for point-based lookups")


# =====================================================================
# 2. VECTORLESS ENGINE & PARSER SERVICE
# =====================================================================
class VectorlessEngine:
    def __init__(self, cache_dir: str = ".vectorless_cache", openai_api_key: Optional[str] = None):
        self.converter = DocumentConverter()
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.client = AsyncOpenAI(api_key=openai_api_key or os.getenv("OPENAI_API_KEY"))

    def compute_file_hash(self, file_path: str) -> str:
        """Computes SHA-256 fingerprint for immutable document caching."""
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
        return hasher.hexdigest()

    def parse_file_to_tree(self, file_path: str) -> TreeNode:
        """
        Converts multi-format files (.pdf, .docx, .xlsx, .pptx) using Docling
        into a clean, nested section hierarchy without breaking tables or sentences.
        """
        logger.info(f"📖 [PARSING] Processing file with Docling: {file_path}")
        conversion_result = self.converter.convert(file_path)
        doc = conversion_result.document

        root = TreeNode(title=doc.name or Path(file_path).name, level=0)
        stack: List[TreeNode] = [root]

        for item, level in doc.iterate_items():
            page_no = item.prov[0].page_no if hasattr(item, "prov") and item.prov else 1

            # Case A: Structural Headers, Titles, or Sheet Names
            if item.label in [DocItemLabel.SECTION_HEADER, DocItemLabel.TITLE]:
                heading_text = item.text.strip()
                heading_level = level if level > 0 else 1

                new_node = TreeNode(
                    title=heading_text,
                    level=heading_level,
                    page_numbers=[page_no]
                )

                while len(stack) > 1 and stack[-1].level >= heading_level:
                    stack.pop()

                stack[-1].children.append(new_node)
                stack.append(new_node)

            # Case B: Content Elements (Paragraphs, Tables, Lists)
            else:
                content_text = ""
                if item.label == DocItemLabel.TABLE:
                    content_text = f"[TABLE]\n{item.export_to_markdown()}"
                elif hasattr(item, "text") and item.text.strip():
                    content_text = item.text.strip()

                if content_text:
                    target_node = stack[-1]
                    target_node.content_blocks.append(content_text)
                    if page_no not in target_node.page_numbers:
                        target_node.page_numbers.append(page_no)

        return root

    async def generate_node_summaries(self, node: TreeNode):
        """Generates fast 1-2 sentence abstracts for each section asynchronously."""
        raw_text = "\n".join(node.content_blocks)
        if raw_text:
            response = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Summarize the key information in this section in 1-2 clear sentences."},
                    {"role": "user", "content": f"Section: {node.title}\nContent:\n{raw_text[:1500]}"}
                ],
                max_tokens=90,
                temperature=0.0
            )
            node.summary = response.choices[0].message.content.strip()
        else:
            node.summary = f"Section topic group under {node.title}"

        if node.children:
            await asyncio.gather(*[self.generate_node_summaries(child) for child in node.children])

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
        """Strips heavy raw content, returning low-token structural metadata for routing."""
        item = {
            "node_id": node.node_id,
            "title": node.title,
            "pages": node.page_numbers,
            "summary": node.summary or "",
        }
        if max_depth is None or current_depth < max_depth:
            item["children"] = [
                self.get_lightweight_index(c, max_depth, current_depth + 1)
                for c in node.children
            ]
        return item


# =====================================================================
# 3. LAYERED ROUTER LOGIC
# =====================================================================
class VectorlessRouter:
    def __init__(self, engine: VectorlessEngine):
        self.engine = engine

    async def route(self, query: str, root_tree: TreeNode) -> Tuple[bool, List[str]]:
        """
        Executes 2-pass layered navigation + query intent classification.
        Pass 1: Inspects Level-1 top chapters & detects global vs point intent.
        Pass 2: If point query, inspects leaf subsections under selected chapters only.
        """
        # PASS 1: Evaluate Top-Level Chapters
        top_level_index = self.engine.get_lightweight_index(root_tree, max_depth=1)

        pass1_prompt = f"""You are a document routing agent.
Analyze the user query against the top-level chapters of the document tree.

Task:
1. Determine if this is a GLOBAL query (e.g., asking for an overall summary, high-level overview, or main themes) or a POINT lookup.
2. If POINT query, select the relevant top-level chapter node_ids.

Top-Level Document Index:
{json.dumps(top_level_index, indent=2)}

User Query: {query}"""

        pass1_res = await self.engine.client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": pass1_prompt}],
            response_format=IntentAndRoutingOutput,
            temperature=0.0
        )

        p1_data = pass1_res.choices[0].message.parsed

        if p1_data.is_global_query:
            logger.info("🌐 [ROUTER] Global query intent detected -> Triggering root summary path.")
            return True, [root_tree.node_id]

        top_chapter_ids = p1_data.target_node_ids
        logger.info(f"🔍 [PASS 1 ROUTING] Target Chapters Selected: {top_chapter_ids}")

        # PASS 2: Detailed Leaf Subsections
        selected_branches = [child for child in root_tree.children if child.node_id in top_chapter_ids]
        if not selected_branches:
            selected_branches = root_tree.children  # Fallback if selection was empty

        sub_branch_index = [self.engine.get_lightweight_index(b) for b in selected_branches]

        pass2_prompt = f"""Select the specific sub-section node_ids that contain the exact answers to the query.

Selected Chapter Trees:
{json.dumps(sub_branch_index, indent=2)}

User Query: {query}"""

        pass2_res = await self.engine.client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": pass2_prompt}],
            response_format=IntentAndRoutingOutput,
            temperature=0.0
        )

        final_node_ids = pass2_res.choices[0].message.parsed.target_node_ids
        logger.info(f"🎯 [PASS 2 ROUTING] Final Target Leaf Node IDs: {final_node_ids}")
        return False, final_node_ids


# =====================================================================
# 4. CONTENT FETCHING & SERVICE WORKFLOW
# =====================================================================
def fetch_node_content(node: TreeNode, target_ids: List[str]) -> List[str]:
    """Retrieves unchunked text and tables strictly from target node IDs."""
    extracted = []
    if node.node_id in target_ids:
        extracted.append(f"### {node.title} (Pages: {node.page_numbers})\n{node.full_content()}")
    for child in node.children:
        extracted.extend(fetch_node_content(child, target_ids))
    return extracted


async def answer_vectorless_query(query: str, file_path: str, engine: VectorlessEngine) -> Dict[str, Any]:
    """End-to-end processing function for an incoming query and file path."""
    file_hash = engine.compute_file_hash(file_path)

    # 1. Ingestion / Cache Lookup
    root_tree = engine.load_tree_from_cache(file_hash)
    if not root_tree:
        root_tree = engine.parse_file_to_tree(file_path)
        logger.info("⚡ Generating section summaries...")
        await engine.generate_node_summaries(root_tree)
        engine.save_tree_to_cache(file_hash, root_tree)

    # 2. Layered Routing
    router = VectorlessRouter(engine)
    is_global, target_ids = await router.route(query, root_tree)

    # 3. Direct Content Retrieval
    if is_global:
        context_str = f"Document Summary: {root_tree.summary}\n\nChapter Overview:\n" + "\n".join([
            f"- {c.title}: {c.summary}" for c in root_tree.children
        ])
    else:
        context_blocks = fetch_node_content(root_tree, target_ids)
        context_str = "\n\n".join(context_blocks)

    # 4. Grounded Synthesis
    synthesis_prompt = f"""Answer the question grounded strictly in the provided document context.
Provide inline citations including section names and page numbers.

Context:
{context_str}

Question: {query}"""

    response = await engine.client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": synthesis_prompt}],
        temperature=0.0
    )

    return {
        "answer": response.choices[0].message.content,
        "is_global": is_global,
        "selected_nodes": target_ids,
        "file_hash": file_hash,
        "usage": response.usage
    }


# =====================================================================
# 5. LANGGRAPH NODE EXECUTION WRAPPER
# =====================================================================
_vectorless_engine_instance = VectorlessEngine()


async def rag_node(state: GraphState) -> Dict[str, Any]:
    """
    LangGraph execution node for the Vectorless RAG Engine.
    Interprets resolved queries from staged action payload and executes page-index RAG.
    """
    logger.info("📚 [RAG NODE] Processing query via Vectorless RAG...")

    resolved_query = state.staged_action_payload.get("resolved_query") if state.staged_action_payload else None
    if not resolved_query and state.messages:
        resolved_query = str(state.messages[-1].content)

    doc_path = state.router_state.last_document_ref

    if not doc_path or not os.path.exists(doc_path):
        return {
            "messages": [AIMessage(content="Please upload a valid document first to proceed with document-grounded Q&A.")],
            "validation_errors": [f"Document path '{doc_path}' not found or unaccessible."]
        }

    try:
        result = await answer_vectorless_query(
            query=resolved_query,
            file_path=doc_path,
            engine=_vectorless_engine_instance
        )

        # Log usage to FinOps Ledger if available
        new_finops_ledger = state.finops_ledger.model_copy(deep=True)
        if "usage" in result and result["usage"]:
            usage = result["usage"]
            new_finops_ledger.log_transaction_usage(
                model_response_metadata={
                    "prompt_tokens": getattr(usage, "prompt_tokens", 0),
                    "completion_tokens": getattr(usage, "completion_tokens", 0),
                    "cache_read_tokens": getattr(usage, "prompt_tokens_details", {}).get("cached_tokens", 0)
                    if hasattr(usage, "prompt_tokens_details") else 0,
                },
                model_pricing_rates={"in": 0.00000015, "cached": 0.000000075, "out": 0.0000006},
            )

        return {
            "messages": [AIMessage(content=result["answer"])],
            "finops_ledger": new_finops_ledger,
            "validation_errors": []
        }

    except Exception as exc:
        logger.error(f"❌ [RAG NODE ERROR] Vectorless query failed: {exc}")
        return {
            "messages": [AIMessage(content="I encountered an issue analyzing the document structure.")],
            "validation_errors": [str(exc)]
        }