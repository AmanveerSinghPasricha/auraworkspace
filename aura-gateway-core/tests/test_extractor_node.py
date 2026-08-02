# tests/test_extractor_node.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from langchain_core.messages import HumanMessage

from app.nodes.extractor import (
    data_extractor_node, 
    ExtractedDataSet, 
    KeyValuePair
)
from app.state import UserProfileContext

@pytest.mark.asyncio
async def test_data_extractor_node_mocked():
    # 1. Prepare Mocked Extracted Data
    mock_extracted_dataset = ExtractedDataSet(
        dataset_title="Quarterly Revenue Summary",
        location_found="Page 1",
        data_points=[
            KeyValuePair(key="total_revenue_usd", value=14500000.0, confidence_score=1.0),
            KeyValuePair(key="peak_demand_mw", value=1450.5, confidence_score=0.95),
        ],
        summary_notes="Extracted from financial overview."
    )

    # Mock raw completion usage for FinOps ledger logging
    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 120
    mock_usage.completion_tokens = 45

    mock_raw_completion = MagicMock()
    mock_raw_completion.usage = mock_usage

    # 2. Mock state input
    input_state = {
        "messages": [
            HumanMessage(content="Extract revenue and demand figures: Revenue is $14.5M, Peak demand is 1450.5 MW.")
        ],
        "user_context": UserProfileContext(user_id="usr_test", department="Engineering"),
        "staged_action_payload": {
            "resolved_query": "Extract revenue and demand figures"
        }
    }

    # 3. Patch instructor client to avoid calling live API endpoints
    with patch(
        "app.nodes.extractor.instructor_client.chat.completions.create_with_completion",
        new_callable=AsyncMock
    ) as mock_create:
        mock_create.return_value = (mock_extracted_dataset, mock_raw_completion)

        # Execute node
        result = await data_extractor_node(input_state)

        # 4. Assertions
        assert "messages" in result
        assert "extracted_data_matrix" in result
        
        # Check generated Markdown output
        markdown_output = result["messages"][0].content
        assert "### ?? Extracted Dataset: Quarterly Revenue Summary" in markdown_output
        assert "| **total_revenue_usd** | 14500000.0 | 100% |" in markdown_output
        assert "| **peak_demand_mw** | 1450.5 | 95% |" in markdown_output

        # Check raw JSON dictionary state
        matrix = result["extracted_data_matrix"]
        assert matrix["dataset_title"] == "Quarterly Revenue Summary"
        assert len(matrix["data_points"]) == 2


@pytest.mark.asyncio
async def test_data_extractor_node_empty_payload():
    """Test resilience when state payload contains no prompt string."""
    empty_state = {
        "messages": [],
        "staged_action_payload": {}
    }

    result = await data_extractor_node(empty_state)

    assert "validation_errors" in result
    assert result["validation_errors"] == ["Empty payload in data_extractor_node."]