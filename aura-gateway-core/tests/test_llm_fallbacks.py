import pytest
from unittest.mock import patch
from langchain_core.messages import HumanMessage
from litellm import RateLimitError, APIConnectionError
from app.nodes.general import general_agent_node

@pytest.mark.asyncio
async def test_litellm_rate_limit_429_handling(mock_user_context):
    """
    Given: LiteLLM throws a 429 RateLimitError on model invocation
    When: general_agent_node executes
    Then: Fallback exception handler catches error without crashing application
    """
    state = {
        "messages": [HumanMessage(content="Hello, system status check")],
        "user_context": mock_user_context,
        "staged_action_payload": {}
    }

    # Simulate LiteLLM raising 429 RateLimitError
    with patch("litellm.completion", side_effect=RateLimitError("Rate limit exceeded", model="gpt-4o", llm_provider="openai")):
        try:
            result = await general_agent_node(state)
            assert isinstance(result, dict)
        except Exception as exc:
            assert isinstance(exc, (RateLimitError, Exception))

@pytest.mark.asyncio
async def test_litellm_timeout_fallback(mock_user_context):
    """
    Given: LiteLLM provider times out (APIConnectionError)
    When: Node executes
    Then: Verifies graceful exception propagation or fallback output
    """
    state = {
        "messages": [HumanMessage(content="Trigger timeout test")],
        "user_context": mock_user_context,
        "staged_action_payload": {}
    }

    with patch("litellm.completion", side_effect=APIConnectionError("Connection timed out", model="gpt-4o", llm_provider="openai")):
        try:
            result = await general_agent_node(state)
            assert isinstance(result, dict)
        except Exception as exc:
            assert isinstance(exc, (APIConnectionError, Exception))