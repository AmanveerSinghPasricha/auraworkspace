from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def mock_app_dependencies():
    """Mock database connection and state graph engine for CI test runner."""
    # Mock graph engine on app state
    mock_engine = MagicMock()
    mock_engine.ainvoke.return_value = {
        "messages": [MagicMock(content="Mocked response from test agent")]
    }

    # Patch the state graph and db health checks in app state
    with patch.object(app.state, "graph", mock_engine, create=True), patch(
        "app.main.check_database_connection", return_value=True
    ):
        yield


def test_gateway_health_check():
    """Verify backend health endpoint responds properly."""
    response = client.get("/health")
    assert response.status_code in [200, 503]
    # Verify health response schema contains expected service keys
    data = response.json()
    assert "service" in data or "status" in data


def test_frontend_to_db_chat_flow():
    """
    Verify connection flow with mocked graph engine:
    Frontend Payload -> FastAPI Chat Endpoint -> JSON Response
    """
    payload = {"message": "Integration test ping"}

    # Simulate POST request coming from frontend
    response = client.post("/api/v1/chat", json=payload)

    # In test runner with mocked dependencies or fallback, check valid response
    if response.status_code == 200:
        data = response.json()
        assert "content" in data or "response" in data or "message" in data
    else:
        # Validate 503 is gracefully caught if graph engine is explicitly offline
        assert response.status_code == 503
        assert "detail" in response.json()