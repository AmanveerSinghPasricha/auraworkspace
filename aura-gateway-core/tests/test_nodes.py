import pytest
from langchain_core.messages import HumanMessage
from app.nodes.pii_security import pii_redaction_node

@pytest.mark.asyncio
async def test_pii_redaction_happy_path(mock_user_context):
    """Standard flow: Redacts email cleanly from state message."""
    state = {
        "messages": [HumanMessage(content="Contact me at john.doe@example.com")],
        "user_context": mock_user_context,
        "staged_action_payload": {},
    }
    result = await pii_redaction_node(state)
    assert "messages" in result
    redacted_content = str(result["messages"][0].content)
    assert "john.doe@example.com" not in redacted_content
    assert "<EMAIL_ADDRESS>" in redacted_content

@pytest.mark.asyncio
async def test_pii_redaction_edge_case_no_pii(mock_user_context):
    """Edge Case: Plain text containing no sensitive data should pass through untouched."""
    plain_text = "Hello team, what is the status of the project?"
    state = {
        "messages": [HumanMessage(content=plain_text)],
        "user_context": mock_user_context,
        "staged_action_payload": {},
    }
    result = await pii_redaction_node(state)
    assert result["messages"][0].content == plain_text

@pytest.mark.asyncio
async def test_pii_redaction_edge_case_multiple_pii_types(mock_user_context):
    """Edge Case: Handles multiple distinct PII types in a single query."""
    mixed_text = "Call 555-019-2831 or email dev@aura.io with SSN 000-12-3456"
    state = {
        "messages": [HumanMessage(content=mixed_text)],
        "user_context": mock_user_context,
        "staged_action_payload": {},
    }
    result = await pii_redaction_node(state)
    redacted_content = str(result["messages"][0].content)
    
    assert "555-019-2831" not in redacted_content
    assert "dev@aura.io" not in redacted_content
    assert "000-12-3456" not in redacted_content