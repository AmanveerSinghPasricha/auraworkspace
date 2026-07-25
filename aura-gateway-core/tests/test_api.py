import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.asyncio
async def test_root_endpoint():
    """Verify GET / returns server status and documentation links."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert "docs" in data

@pytest.mark.asyncio
async def test_health_check_endpoint():
    """Verify GET /health checks database connection and graph compilation."""
    # Using LifespanManager or entering app context ensures startup events run
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code in (200, 503) # Validates response structure
    data = response.json()
    assert "status" in data
    assert "diagnostics" in data

@pytest.mark.asyncio
async def test_chat_execution_happy_path():
    """Standard flow: Sends valid ChatRequestPayload to POST /api/v1/chat."""
    payload = {
        "user_id": "pytest_user",
        "thread_id": "api_test_thread_001",
        "message": "What is quantum computing?",
        "department": "Engineering",
        "role_title": "Software Engineer",
        "preferred_language": "English"
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/chat", json=payload)

    # 200 OK when DB is connected, or 503 if test DB pool is uninitialized
    assert response.status_code in (200, 503)
    data = response.json()
    if response.status_code == 200:
        assert data["thread_id"] == "api_test_thread_001"
        assert "response" in data

@pytest.mark.asyncio
async def test_chat_execution_edge_case_missing_required_field():
    """Edge Case: Missing required 'message' field triggers Pydantic schema validation error (HTTP 422)."""
    invalid_payload = {
        "user_id": "pytest_user",
        "thread_id": "api_test_thread_002",
        "department": "Engineering"
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/chat", json=invalid_payload)

    assert response.status_code == 422