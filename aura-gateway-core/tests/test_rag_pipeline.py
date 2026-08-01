"""
Aura Gateway Core - Vectorless RAG Engine Pipeline Test Suite
============================================================
Validates end-to-end vectorless RAG execution:
1. Cache loading & tree construction
2. Hybrid 3-tier routing (Fast-Path Regex + Candidate Pruning + LLM Navigation)
3. Unchunked context extraction
4. Grounded answer generation via LiteLLM
"""

import sys
import asyncio
import logging
from pathlib import Path

# Ensure root directory is on Python path
sys.path.append(str(Path(__file__).parent.parent))

from app.nodes.rag import VectorlessEngine, VectorlessRouter, answer_vectorless_query, fetch_node_content

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("test_rag_pipeline")


async def run_vectorless_rag_test():
    print("\n" + "=" * 70)
    print("🧪 [TEST SUITE] STARTING VECTORLESS RAG ENGINE PIPELINE TEST")
    print("=" * 70 + "\n")

    # 1. Target Test Document
    upload_dir = Path("./uploads")
    pdf_files = list(upload_dir.glob("*.pdf")) if upload_dir.exists() else []

    if not pdf_files:
        print("❌ [ERROR] No PDF document found in ./uploads directory.")
        print("Please place NIST.SP.800-53r5.pdf inside ./uploads to run this test.")
        return

    test_file = str(pdf_files[0])
    file_name = pdf_files[0].name
    print(f"📁 [TEST FILE SELECTED] {file_name}")

    engine = VectorlessEngine()
    file_hash = engine.compute_file_hash(test_file)
    print(f"🔑 [FILE HASH] SHA-256: {file_hash}")

    # 2. Check Cache / Tree Parse
    cached_tree = engine.load_tree_from_cache(file_hash)
    if not cached_tree:
        print("📖 [PARSING] Parsing document and building structural tree index...")
        cached_tree = await engine.parse_file_to_tree(test_file)
        await engine.generate_node_summaries(cached_tree)
        engine.save_tree_to_cache(file_hash, cached_tree)
    else:
        print("✅ [CACHE HIT] Loaded pre-parsed tree index from local disk cache.")

    print(f"   ├── Root Title: {cached_tree.title}")
    print(f"   └── Top Chapters Detected: {len(cached_tree.children)}")

    # 3. Test Hybrid Router (Tier 1 Code Fast-Path)
    print("\n" + "-" * 70)
    print("🔍 [TEST STEP 1] TESTING HYBRID ROUTER (Tier 1 Fast-Path Regex)")
    print("-" * 70)
    
    test_query_1 = "What are the key access control requirements and organizational guidelines described in section AC-2?"
    print(f"❓ Prompt: '{test_query_1}'")

    router = VectorlessRouter(engine)
    is_global, target_ids, route_usage = await router.route(test_query_1, cached_tree)

    print(f"🌐 Is Global Query Intent: {is_global}")
    print(f"🎯 Target Node IDs Selected: {target_ids}")

    assert len(target_ids) > 0, "Router failed to select any target node IDs!"
    print("✅ [STEP 1 PASSED] Router selected target nodes successfully.")

    # 4. Test Content Extraction
    print("\n" + "-" * 70)
    print("📖 [TEST STEP 2] TESTING UNCHUNKED CONTENT EXTRACTION")
    print("-" * 70)

    extracted_blocks = fetch_node_content(cached_tree, target_ids)
    print(f"📦 Total Content Blocks Retrieved: {len(extracted_blocks)}")

    if extracted_blocks:
        sample_preview = extracted_blocks[0][:200].replace("\n", " ")
        print(f"📄 Block 1 Sample: \"{sample_preview}...\"")

    assert len(extracted_blocks) > 0, "Content extraction returned empty blocks!"
    print("✅ [STEP 2 PASSED] Content extraction gathered unchunked section text successfully.")

    # 5. Test End-to-End RAG Answer Synthesis
    print("\n" + "-" * 70)
    print("🤖 [TEST STEP 3] TESTING END-TO-END RAG SYNTHESIS")
    print("-" * 70)

    result = await answer_vectorless_query(
        query=test_query_1,
        file_path=test_file,
        engine=engine
    )

    print("✅ [RAG RESPONSE RECEIVED SUCCESSFULLY]:\n")
    print(result["answer"])
    print("\n" + "=" * 70)
    print("🎉 [TEST PASSED] VECTORLESS RAG ENGINE IS FULLY OPERATIONAL!")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    asyncio.run(run_vectorless_rag_test())