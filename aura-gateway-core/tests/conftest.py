import os
import sys
import pytest
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=BASE_DIR / ".env", override=False)

# Force tests to use SQLite in-memory DB instead of remote Neon Postgres
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


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