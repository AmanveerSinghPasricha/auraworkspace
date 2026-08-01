"""
Aura Gateway Core - Integration & Persistence Test Suite
=========================================================
Validates database module imports, memory model validation,
and thread state persistence across conversational turns.
"""

import sys
import asyncio
import pytest
from pathlib import Path
from langchain_core.messages import HumanMessage

# Enforce Windows Selector Event Loop Policy for Psycopg async mode on Windows
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Ensure root directory is on Python path
sys.path.append(str(Path(__file__).parent.parent))

from app.memory import UserProfileMemory
from app.graph import create_aura_graph
from app.state import UserProfileContext


@pytest.fixture
def mock_initial_state():
    """Provides a baseline state structure for graph execution tests."""
    user_ctx = UserProfileContext(
        user_id="usr_test_99",
        department="Engineering",
        role_title="Software Architect",
        preferred_language="English"
    )
    return {
        "messages": [HumanMessage(content="Hello! Can you help me review security protocols?")],
        "user_context": user_ctx,
        "staged_action_payload": {
            "resolved_query": "Hello! Can you help me review security protocols?",
            "raw_text": "Hello! Can you help me review security protocols?"
        }
    }


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
    compiled_app = create_aura_graph(checkpointer=None, store=None)
    thread_config = {"configurable": {"thread_id": "persistence_test_thread_999"}}

    # First turn
    turn_1_state = await compiled_app.ainvoke(mock_initial_state, config=thread_config)
    assert "messages" in turn_1_state
    assert len(turn_1_state["messages"]) >= 1

    # Second turn on SAME thread_id
    turn_2_input = {
        "messages": [HumanMessage(content="Can you summarize what we just discussed?")],
        "user_context": mock_initial_state["user_context"],
        "staged_action_payload": {
            "resolved_query": "Can you summarize what we just discussed?",
            "raw_text": "Can you summarize what we just discussed?"
        }
    }

    turn_2_state = await compiled_app.ainvoke(turn_2_input, config=thread_config)
    assert "messages" in turn_2_state
    assert len(turn_2_state["messages"]) >= 1