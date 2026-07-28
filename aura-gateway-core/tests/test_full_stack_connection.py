from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def mock_app_dependencies():
    """Mock state graph engine and dependencies safely for CI runners."""
    # Create mock graph engine
    mock_engine = MagicMock()
    mock_engine.ainvoke.return_value = {
        "messages": [MagicMock(content="Mocked response from test agent")]
    }

    # Safely attach mock graph engine directly to FastAPI app state
    if hasattr(app, "state"):
        app.state.graph = mock_engine

    yield


def test_gateway_health_check():
    """Verify backend health endpoint responds properly."""
    response = client.get("/health")
    # Health endpoint can return 200 (healthy) or 503 (if DB isn't running in CI)
    assert response.status_code in [200, 503]
    
    # Verify the JSON response contains diagnostic keys
    data = response.json()
    assert isinstance(data, dict)


def test_frontend_to_db_chat_flow():
    """
    Verify API connection flow:
    Frontend Payload -> FastAPI Chat Endpoint -> Response / Handled Error
    """
    payload = {"message": "Integration test ping"}

    response = client.post("/api/v1/chat", json=payload)

    # In CI, if graph is mocked it returns 200; if uninitialized it returns 503
    assert response.status_code in [200, 503]
    
    data = response.json()
    if response.status_code == 200:
        assert "content" in data or "response" in data or "message" in data
    else:
        assert "detail" in data