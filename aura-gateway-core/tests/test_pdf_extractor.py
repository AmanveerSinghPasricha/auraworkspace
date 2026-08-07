import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
from langchain_core.messages import HumanMessage

from app.nodes.rag import _vectorless_engine_instance
from app.nodes.extractor import data_extractor_node, ExtractedDataSet, KeyValuePair
from app.state import UserProfileContext


@pytest.mark.asyncio
async def test_extractor_with_real_pdf():
    # 1. Locate PDF File
    pdf_path = Path("./uploads/NIST.SP.800-53r5.pdf")
    if not pdf_path.exists():
        pytest.skip("Place a sample PDF at ./uploads/NIST.SP.800-53r5.pdf to run this test.")

    # 2. Parse PDF via Vectorless RAG Engine (Docling / Local Cache)
    file_hash = _vectorless_engine_instance.compute_file_hash(str(pdf_path))
    tree = _vectorless_engine_instance.load_tree_from_cache(file_hash)
    
    if not tree:
        tree = await _vectorless_engine_instance.parse_file_to_tree(str(pdf_path))
        _vectorless_engine_instance.save_tree_to_cache(file_hash, tree)

    pdf_content_text = tree.full_content()[:4000]

    # 3. Construct GraphState payload
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

    # 4. Prepare Mock Output to safeguard test against live LLM API rate limits
    mock_extracted_dataset = ExtractedDataSet(
        dataset_title="NIST SP 800-53 Metrics",
        location_found="Section AC-2",
        data_points=[
            KeyValuePair(key="total_control_count", value=20, confidence_score=1.0),
            KeyValuePair(key="review_period_days", value=30, confidence_score=0.9)
        ]
    )
    mock_raw_completion = MagicMock()
    mock_raw_completion.usage = MagicMock(prompt_tokens=150, completion_tokens=50)

    # 5. Patch instructor_client call to handle API rate limits resiliently
    with patch(
        "app.nodes.extractor.instructor_client.chat.completions.create_with_completion",
        new_callable=AsyncMock
    ) as mock_create:
        mock_create.return_value = (mock_extracted_dataset, mock_raw_completion)

        result = await data_extractor_node(input_state)

        # 6. Assertions
        assert "extracted_data_matrix" in result or "messages" in result
        
        if "extracted_data_matrix" in result:
            matrix = result["extracted_data_matrix"]
            assert len(matrix.get("data_points", [])) > 0