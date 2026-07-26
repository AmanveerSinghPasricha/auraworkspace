import pytest
from langchain_core.messages import HumanMessage
from app.graph import create_aura_graph

def test_graph_compilation_and_structure():
    """Verify that the state graph compiles without errors and contains all core architecture nodes."""
    compiled_app = create_aura_graph()
    assert compiled_app is not None

    graph_nodes = set(compiled_app.get_graph().nodes.keys())

    # Assert presence of all architectural nodes
    assert "pii_redaction" in graph_nodes
    assert "supervisor_router" in graph_nodes
    assert "general_agent" in graph_nodes
    assert "rag_engine" in graph_nodes
    assert "data_extractor" in graph_nodes

@pytest.mark.asyncio
async def test_full_graph_invocation_happy_path(mock_initial_state):
    """Standard flow: Invokes query through compiled graph end-to-end."""
    compiled_app = create_aura_graph()
    config = {"configurable": {"thread_id": "pytest_thread_101"}}

    final_state = await compiled_app.ainvoke(mock_initial_state, config=config)

    assert "messages" in final_state
    assert len(final_state["messages"]) >= 1
    final_response = str(final_state["messages"][-1].content)
    assert len(final_response) > 0

@pytest.mark.asyncio
async def test_graph_edge_case_ambiguous_prompt(mock_user_context):
    """Edge Case: Ambiguous or gibberish prompt should fall back gracefully without raising an exception."""
    compiled_app = create_aura_graph()
    config = {"configurable": {"thread_id": "pytest_edge_thread_102"}}

    state = {
        "messages": [HumanMessage(content="asdfghjkl123456")],
        "user_context": mock_user_context,
        "staged_action_payload": {"resolved_query": "asdfghjkl123456"},
    }

    final_state = await compiled_app.ainvoke(state, config=config)
    assert "messages" in final_state
    assert len(final_state["messages"]) >= 1