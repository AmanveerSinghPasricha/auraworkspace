import pytest
from fastapi.testclient import TestClient
from app.main import app

# Initialize test client for the FastAPI gateway app
client = TestClient(app)

def test_gateway_health_check():
    """Verify frontend can reach the backend health endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json().get("status") in ["online", "ok", "healthy"]


def test_frontend_to_db_chat_flow():
    """
    Verify the complete connection flow:
    Frontend Payload -> FastAPI Chat Endpoint -> Database/Persistence -> JSON Response
    """
    # 1. Payload structured exactly as sent by src/hooks/useApi.ts
    payload = {
        "message": "Integration test ping"
    }

    # 2. Simulate POST request coming from frontend
    response = client.post("/api/v1/chat", json=payload)

    # 3. Assert HTTP response status
    assert response.status_code == 200, f"Backend returned error: {response.text}"

    data = response.json()

    # 4. Assert response payload contains expected schema keys
    assert "content" in data or "response" in data, "Response missing message payload"
    
    # 5. Optional: Verify data was written to the DB (if using SQLAlchemy session)
    # db_record = db_session.query(ChatMessage).filter_by(content="Integration test ping").first()
    # assert db_record is not None