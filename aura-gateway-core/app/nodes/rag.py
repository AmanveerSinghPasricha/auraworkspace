"""
Aura Gateway Core - Production Vectorless RAG Engine
===================================================
Layout-aware, structure-first RAG engine using Docling layout parsing,
LiteLLM Gateway integration, dual-tree index navigation, layered multi-pass routing,
and immutable filesystem caching. Integrated with LangGraph state.
"""

import os
import sys
import json
import uuid
import logging
import hashlib
import asyncio
import pypdf
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from pydantic import BaseModel, Field

# Raise recursion limit for ultra-deep 400+ page document structures
sys.setrecursionlimit(5000)

# Layout Parsing Engine & PDFium Backend
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.datamodel.base_models import InputFormat
from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
from docling_core.types.doc import DocItemLabel

# Gateway Interoperability SDK (LiteLLM + Instructor)
import instructor
from litellm import acompletion

# LangGraph Core Integrations & Centralized Settings
from langchain_core.messages import AIMessage
from app.config import settings
from app.state import GraphState

logger = logging.getLogger("vectorless_rag")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Force C++ memory allocators to trim unused heap memory back to OS
os.environ["MALLOC_TRIM_THRESHOLD_"] = "65536"
os.environ["OMP_NUM_THREADS"] = "2"

# Wrap LiteLLM with Instructor for Gateway Structured Output calls
instructor_client = instructor.from_litellm(acompletion)


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
        """Iteratively extracts unchunked text and tables for this node and children."""
        text_blocks = [ "\n".join(self.content_blocks) ]
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
        # Configure lightweight options to keep RAM low during batch execution
        pipeline_options = PdfPipelineOptions()
        pipeline_options.generate_page_images = False
        pipeline_options.do_ocr = False  # Disable OCR to prevent memory spikes
        pipeline_options.do_table_structure = True  # Retain structural table extraction
        
        self.converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    pipeline_options=pipeline_options,
                    backend=PyPdfiumDocumentBackend  # Uses PDFium backend to bypass C++ bad_alloc bug on Windows
                )
            }
        )
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def compute_file_hash(self, file_path: str) -> str:
        """Computes SHA-256 fingerprint for immutable document caching."""
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
        return hasher.hexdigest()

    def _parse_single_doc_to_tree(self, doc, root_title: str) -> TreeNode:
        """Internal helper to convert a Docling Document object into a TreeNode structure."""
        root = TreeNode(title=root_title, level=0)
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

    def parse_file_to_tree(self, file_path: str, batch_size: int = 15) -> TreeNode:
        """
        Converts multi-format files using Docling and PyPdfium.
        Uses 15-page batching via temporary sub-PDFs for large files to keep RAM lightweight.
        """
        logger.info(f"📖 [PARSING] Processing file with Docling (PyPdfium): {file_path}")
        root_title = Path(file_path).name

        total_pages = 0
        if file_path.lower().endswith(".pdf"):
            try:
                reader = pypdf.PdfReader(file_path)
                total_pages = len(reader.pages)
            except Exception as e:
                logger.warning(f"Failed to inspect PDF page count via PyPDF: {e}")

        # Batch process large PDFs
        if total_pages > batch_size:
            logger.info(f"📄 [PARSING BATCHED] Document has {total_pages} pages. Processing in batches of {batch_size} pages...")
            
            accumulated_children: List[TreeNode] = []
            reader = pypdf.PdfReader(file_path)
            temp_dir = Path("./uploads/_temp_chunks")
            temp_dir.mkdir(parents=True, exist_ok=True)
            
            for start_page in range(1, total_pages + 1, batch_size):
                end_page = min(start_page + batch_size - 1, total_pages)
                
                logger.info(f"📑 Processing pages {start_page} to {end_page} of {total_pages}...")
                
                # Extract chunk to temporary PDF file
                writer = pypdf.PdfWriter()
                for p_idx in range(start_page - 1, end_page):
                    writer.add_page(reader.pages[p_idx])
                
                chunk_path = temp_dir / f"chunk_{start_page}_{end_page}.pdf"
                with open(chunk_path, "wb") as f_out:
                    writer.write(f_out)

                try:
                    conv_res = self.converter.convert(str(chunk_path))
                    if conv_res and conv_res.document:
                        batch_root = self._parse_single_doc_to_tree(conv_res.document, root_title)
                        
                        # Adjust page numbers to match original document offset
                        for child in batch_root.children:
                            child.page_numbers = [p + start_page - 1 for p in child.page_numbers]
                        
                        accumulated_children.extend(batch_root.children)
                        if batch_root.content_blocks:
                            accumulated_children.append(
                                TreeNode(
                                    title=f"Page Group {start_page}-{end_page}",
                                    level=1,
                                    page_numbers=list(range(start_page, end_page + 1)),
                                    content_blocks=batch_root.content_blocks
                                )
                            )
                except Exception as batch_err:
                    logger.error(f"❌ Failed to parse page range {start_page}-{end_page}: {batch_err}")
                finally:
                    if chunk_path.exists():
                        chunk_path.unlink()  # Cleanup temp chunk file

            final_root = TreeNode(title=root_title, level=0, children=accumulated_children)
            return final_root

        # Standard conversion for small documents
        conversion_result = self.converter.convert(file_path)
        return self._parse_single_doc_to_tree(conversion_result.document, root_title)

    async def generate_node_summaries(self, root_node: TreeNode):
        """Generates fast section summaries using an iterative BFS queue to avoid recursion stack limits."""
        all_nodes: List[TreeNode] = []
        queue = [root_node]
        
        # Flatten tree using BFS
        while queue:
            curr = queue.pop(0)
            all_nodes.append(curr)
            if curr.children:
                queue.extend(curr.children)

        semaphore = asyncio.Semaphore(10)  # Rate-limit concurrency

        async def summarize_node(node: TreeNode):
            raw_text = "\n".join(node.content_blocks)
            if not raw_text:
                node.summary = f"Section topic group under {node.title}"
                return

            async with semaphore:
                try:
                    response = await acompletion(
                        model=settings.LLM_RAG_PRIMARY,
                        messages=[
                            {"role": "system", "content": "Summarize the key information in this section in 1-2 clear sentences."},
                            {"role": "user", "content": f"Section: {node.title}\nContent:\n{raw_text[:1500]}"}
                        ],
                        max_tokens=90,
                        temperature=0.0,
                        fallbacks=[settings.LLM_RAG_FALLBACK],
                        num_retries=2,
                    )
                    node.summary = response.choices[0].message.content.strip()
                except Exception as e:
                    logger.warning(f"Failed to generate summary for section '{node.title}': {e}")
                    node.summary = f"Section text content under {node.title}"

        # Run summaries concurrently across collected nodes safely
        await asyncio.gather(*[summarize_node(n) for n in all_nodes])

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
# 3. LAYERED ROUTER LOGIC (Gateway Unified Call with Failover)
# =====================================================================
class VectorlessRouter:
    def __init__(self, engine: VectorlessEngine):
        self.engine = engine

    async def route(self, query: str, root_tree: TreeNode) -> Tuple[bool, List[str], Any]:
        """
        Executes 2-pass layered navigation + query intent classification using Instructor + LiteLLM.
        Pass 1: Inspects Level-1 top chapters & detects global vs point intent.
        Pass 2: If point query, inspects leaf subsections under selected chapters only.
        Automatically falls back to Nvidia Nemotron if Gemini hits rate limits.
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

        p1_data, pass1_raw = await instructor_client.chat.completions.create_with_completion(
            model=settings.LLM_RAG_PRIMARY,
            messages=[{"role": "user", "content": pass1_prompt}],
            response_model=IntentAndRoutingOutput,
            temperature=0.0,
            fallbacks=[settings.LLM_RAG_FALLBACK],
            max_retries=2,
        )

        if p1_data.is_global_query:
            logger.info("🌐 [ROUTER] Global query intent detected -> Triggering root summary path.")
            return True, [root_tree.node_id], getattr(pass1_raw, "usage", None)

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

        p2_data, pass2_raw = await instructor_client.chat.completions.create_with_completion(
            model=settings.LLM_RAG_PRIMARY,
            messages=[{"role": "user", "content": pass2_prompt}],
            response_model=IntentAndRoutingOutput,
            temperature=0.0,
            fallbacks=[settings.LLM_RAG_FALLBACK],
            max_retries=2,
        )

        final_node_ids = p2_data.target_node_ids
        logger.info(f"🎯 [PASS 2 ROUTING] Final Target Leaf Node IDs: {final_node_ids}")
        return False, final_node_ids, getattr(pass2_raw, "usage", None)


# =====================================================================
# 4. CONTENT FETCHING & SERVICE WORKFLOW
# =====================================================================
def fetch_node_content(node: TreeNode, target_ids: List[str]) -> List[str]:
    """Retrieves unchunked text and tables strictly from target node IDs iteratively."""
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
    """End-to-end processing function for an incoming query and file path using Gateway calls with Rate-Limit Failover."""
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
    is_global, target_ids, route_usage = await router.route(query, root_tree)

    # 3. Direct Content Retrieval
    if is_global:
        context_str = f"Document Summary: {root_tree.summary}\n\nChapter Overview:\n" + "\n".join([
            f"- {c.title}: {c.summary}" for c in root_tree.children
        ])
    else:
        context_blocks = fetch_node_content(root_tree, target_ids)
        context_str = "\n\n".join(context_blocks)

    # 4. Grounded Synthesis via Gateway LLM (Gemini 2.5 Flash + Nvidia Nemotron Failover)
    synthesis_prompt = f"""Answer the question grounded strictly in the provided document context.
Provide inline citations including section names and page numbers.

Context:
{context_str}

Question: {query}"""

    response = await acompletion(
        model=settings.LLM_RAG_PRIMARY,
        messages=[{"role": "user", "content": synthesis_prompt}],
        temperature=0.0,
        fallbacks=[settings.LLM_RAG_FALLBACK],
        num_retries=2,
    )

    return {
        "answer": response.choices[0].message.content,
        "is_global": is_global,
        "selected_nodes": target_ids,
        "file_hash": file_hash,
        "usage": getattr(response, "usage", None)
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
    logger.info("📚 [RAG NODE] Processing query via Vectorless RAG Engine...")

    # Safely extract state attributes whether state is a dict or GraphState object
    staged_payload = state.get("staged_action_payload") if isinstance(state, dict) else getattr(state, "staged_action_payload", {})
    messages = state.get("messages", []) if isinstance(state, dict) else getattr(state, "messages", [])
    router_state = state.get("router_state") if isinstance(state, dict) else getattr(state, "router_state", None)

    resolved_query = staged_payload.get("resolved_query") if staged_payload else None
    if not resolved_query and messages:
        raw_msg = messages[-1].content
        resolved_query = raw_msg if isinstance(raw_msg, str) else str(raw_msg)

    doc_path = getattr(router_state, "last_document_ref", None) if router_state else None

    if not doc_path or not os.path.exists(doc_path):
        return {
            "messages": [AIMessage(content="Please upload a valid document first to proceed with document-grounded Q&A.")],
            "validation_errors": [f"Document path '{doc_path}' not found or inaccessible."]
        }

    try:
        result = await answer_vectorless_query(
            query=resolved_query,
            file_path=doc_path,
            engine=_vectorless_engine_instance
        )

        # Log usage to FinOps Ledger
        finops_ledger = state.get("finops_ledger") if isinstance(state, dict) else getattr(state, "finops_ledger", None)
        new_finops_ledger = finops_ledger.model_copy(deep=True) if finops_ledger else None

        if new_finops_ledger and result.get("usage"):
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

        res = {
            "messages": [AIMessage(content=result["answer"])],
            "validation_errors": []
        }
        if new_finops_ledger:
            res["finops_ledger"] = new_finops_ledger
        return res

    except Exception as exc:
        logger.error(f"❌ [RAG NODE ERROR] Vectorless query failed: {exc}")
        return {
            "messages": [AIMessage(content="I encountered an issue analyzing the document structure across primary and fallback inference endpoints.")],
            "validation_errors": [str(exc)]
        }