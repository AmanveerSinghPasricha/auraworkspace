import pytest
from langchain_core.messages import HumanMessage
from app.state import UserProfileContext

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