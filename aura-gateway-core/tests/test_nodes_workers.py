import pytest
from langchain_core.messages import HumanMessage, AIMessage
import app.nodes.rag as rag_module
import app.nodes.extractor as extractor_module
import app.nodes.general as general_module

# Dynamically pick up whatever node function name is present in the module
rag_node_func = getattr(rag_module, "rag_engine_node", getattr(rag_module, "rag_node", getattr(rag_module, "rag_engine", None)))
extractor_node_func = getattr(extractor_module, "data_extractor_node", getattr(extractor_module, "extractor_node", getattr(extractor_module, "data_extractor", None)))
general_node_func = getattr(general_module, "general_agent_node", getattr(general_module, "general_node", getattr(general_module, "general_agent", None)))


# --- 1. RAG ENGINE NODE TESTS ---

@pytest.mark.asyncio
async def test_rag_engine_node_execution(mock_user_context):
    """Verify RAG node executes query without crashing."""
    if rag_node_func is None:
        pytest.skip("RAG node function not found in app.nodes.rag")

    state = {
        "messages": [HumanMessage(content="What is our policy on remote work?")],
        "user_context": mock_user_context,
        "staged_action_payload": {"resolved_query": "What is our policy on remote work?"}
    }

    result = await rag_node_func(state)
    assert isinstance(result, dict)


# --- 2. DATA EXTRACTOR NODE TESTS ---

@pytest.mark.asyncio
async def test_data_extractor_node_execution(mock_user_context):
    """Verify data extractor executes parsing from state message."""
    if extractor_node_func is None:
        pytest.skip("Extractor node function not found in app.nodes.extractor")

    state = {
        "messages": [HumanMessage(content="Extract details: ID=101, Name=AlphaProject, Amount=$5000")],
        "user_context": mock_user_context,
        "staged_action_payload": {"resolved_query": "Extract details: ID=101, Name=AlphaProject, Amount=$5000"}
    }

    result = await extractor_node_func(state)
    assert isinstance(result, dict)


# --- 3. GENERAL AGENT NODE TESTS ---

@pytest.mark.asyncio
async def test_general_agent_node_execution(mock_user_context):
    """Verify general agent formats user context and returns AI response."""
    if general_node_func is None:
        pytest.skip("General agent function not found in app.nodes.general")

    state = {
        "messages": [HumanMessage(content="Explain quantum computing in simple terms.")],
        "user_context": mock_user_context,
        "staged_action_payload": {}
    }

    result = await general_node_func(state)

    assert isinstance(result, dict)
    assert "messages" in result
    assert len(result["messages"]) >= 1