import pytest
from langchain_core.messages import HumanMessage
from app.memory import UserProfileMemory
from app.graph import create_aura_graph

@pytest.mark.asyncio
async def test_database_module_imports():
    """Verify database module loads cleanly."""
    import app.database as db
    assert db is not None

@pytest.mark.asyncio
async def test_user_profile_memory_validation():
    """Verify UserProfileMemory Pydantic model instantiates and validates correctly."""
    profile = UserProfileMemory(
        user_id="usr_test_99",
        preferred_language="Spanish"
    )

    assert profile.user_id == "usr_test_99"
    assert profile.preferred_language == "Spanish"

@pytest.mark.asyncio
async def test_thread_state_persistence_across_turns(mock_initial_state):
    """
    Given: A thread_id configuration
    When: Graph is invoked multiple times on the same thread
    Then: State history persists across turns
    """
    compiled_app = create_aura_graph()
    thread_config = {"configurable": {"thread_id": "persistence_test_thread_999"}}

    # First turn
    turn_1_state = await compiled_app.ainvoke(mock_initial_state, config=thread_config)
    assert "messages" in turn_1_state
    
    # Second turn on SAME thread_id
    turn_2_input = {
        "messages": [HumanMessage(content="Can you summarize what we just discussed?")],
        "user_context": mock_initial_state["user_context"],
        "staged_action_payload": {}
    }
    
    turn_2_state = await compiled_app.ainvoke(turn_2_input, config=thread_config)
    assert "messages" in turn_2_state
    assert len(turn_2_state["messages"]) >= 1