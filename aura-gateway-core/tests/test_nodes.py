import pytest
from langchain_core.messages import HumanMessage
from app.nodes.pii_security import pii_redaction_node

@pytest.mark.asyncio
async def test_pii_redaction_happy_path(mock_user_context):
    """Standard flow: Redacts sensitive entities like phone numbers."""
    state = {
        "messages": [HumanMessage(content="Contact me at 555-019-2831")],
        "user_context": mock_user_context,
        "staged_action_payload": {},
    }
    result = await pii_redaction_node(state)
    assert "messages" in result
    redacted_content = str(result["messages"][-1].content)
    assert "555-019-2831" not in redacted_content
    assert "<PHONE_NUMBER>" in redacted_content


@pytest.mark.asyncio
async def test_pii_redaction_edge_case_no_pii(mock_user_context):
    plain_text = "Hello team, what is the status of the project?"
    state = {
        "messages": [HumanMessage(content=plain_text)],
        "user_context": mock_user_context,
        "staged_action_payload": {},
    }
    result = await pii_redaction_node(state)
    assert result.get("validation_errors") == []


@pytest.mark.asyncio
async def test_pii_redaction_edge_case_multiple_pii_types(mock_user_context):
    mixed_text = "Call 555-019-2831 or message dev team for details"
    state = {
        "messages": [HumanMessage(content=mixed_text)],
        "user_context": mock_user_context,
        "staged_action_payload": {},
    }
    result = await pii_redaction_node(state)
    assert "messages" in result
    redacted_content = str(result["messages"][-1].content)
    assert "555-019-2831" not in redacted_content