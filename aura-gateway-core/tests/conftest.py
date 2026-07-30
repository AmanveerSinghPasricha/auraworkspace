import os
import sys
import asyncio
import pytest
import pytest_asyncio
from pathlib import Path
from dotenv import load_dotenv

# Force load .env if present locally
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=BASE_DIR / ".env", override=False)

# Fallback to in-memory SQLite if no DATABASE_URL is set or if it defaults to localhost
if not os.getenv("DATABASE_URL") or "localhost" in os.getenv("DATABASE_URL", ""):
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

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


@pytest.fixture
def mock_user_context():
    """Provides a reusable mock UserProfileContext."""
    from app.state import UserProfileContext
    return UserProfileContext(
        user_id="test_user_01",
        department="Engineering",
        role_title="AI Engineer",
        preferred_language="English",
    )


@pytest.fixture
def mock_initial_state(mock_user_context):
    """Provides a complete initial GraphState input dictionary."""
    from langchain_core.messages import HumanMessage
    return {
        "messages": [HumanMessage(content="Hello, what can you do?")],
        "user_context": mock_user_context,
        "staged_action_payload": {
            "resolved_query": "Hello, what can you do?",
            "raw_text": "Hello, what can you do?",
        },
    }