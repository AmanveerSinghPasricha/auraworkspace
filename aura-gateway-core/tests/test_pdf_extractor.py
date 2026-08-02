import pytest
import os
from pathlib import Path
from langchain_core.messages import HumanMessage

from app.nodes.rag import _vectorless_engine_instance
from app.nodes.extractor import data_extractor_node
from app.state import UserProfileContext

@pytest.mark.asyncio
async def test_extractor_with_real_pdf():
    # 1. Locate PDF File
    pdf_path = Path("./uploads/NIST.SP.800-53r5.pdf")
    if not pdf_path.exists():
        pytest.skip("Place a sample PDF at ./uploads/sample_report.pdf to run this test.")

    # 2. Parse PDF via Vectorless RAG Engine (Docling)
    file_hash = _vectorless_engine_instance.compute_file_hash(str(pdf_path))
    tree = _vectorless_engine_instance.load_tree_from_cache(file_hash)
    
    if not tree:
        tree = await _vectorless_engine_instance.parse_file_to_tree(str(pdf_path))
        _vectorless_engine_instance.save_tree_to_cache(file_hash, tree)

    # Extract text from the parsed document tree
    pdf_content_text = tree.full_content()[:4000]  # Cap length for context limit

    # 3. Construct GraphState payload with PDF text
    input_state = {
        "messages": [
            HumanMessage(
                content=f"Document Text:\n{pdf_content_text}\n\n"
                        "Task: Extract all key operational metrics, counts, and financial values from this text into clean snake_case fields."
            )
        ],
        "user_context": UserProfileContext(user_id="usr_pdf_test"),
        "staged_action_payload": {
            "resolved_query": "Extract operational metrics into a structured matrix.",
            "document_ref": str(pdf_path)
        }
    }

    # 4. Execute Extractor Node
    result = await data_extractor_node(input_state)

    # 5. Validation Assertions
    assert result["validation_errors"] == []
    assert "extracted_data_matrix" in result
    
    matrix = result["extracted_data_matrix"]
    print("\n--- Extracted PDF Dataset Title ---")
    print(matrix.get("dataset_title"))
    
    print("\n--- Extracted Data Points ---")
    for point in matrix.get("data_points", []):
        print(f"Key: {point['key']} | Value: {point['value']} | Confidence: {point['confidence_score']}")

    assert len(matrix.get("data_points", [])) > 0, "Failed to extract data points from PDF context."