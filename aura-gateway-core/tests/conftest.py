import sys
import asyncio
import pytest
import pytest_asyncio
from langchain_core.messages import HumanMessage
from app.state import UserProfileContext
from app.db import engine

# Fix Psycopg/asyncpg event loop policy on Windows
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest_asyncio.fixture(scope="session", autouse=True)
def event_loop():
    """Provides a session-wide event loop for all async tests."""
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(autouse=True)
async def cleanup_db_engine():
    """Disposes stale asyncpg pool connections between tests."""
    yield
    await engine.dispose()


@pytest.fixture
def mock_user_context():
    """Provides a reusable mock UserProfileContext."""
    return UserProfileContext(
        user_id="test_user_01",
        department="Engineering",
        role_title="AI Engineer",
        preferred_language="English",
    )


@pytest.fixture
def mock_initial_state(mock_user_context):
    """Provides a complete initial GraphState input dictionary."""
    return {
        "messages": [HumanMessage(content="Hello, what can you do?")],
        "user_context": mock_user_context,
        "staged_action_payload": {
            "resolved_query": "Hello, what can you do?",
            "raw_text": "Hello, what can you do?",
        },
    }