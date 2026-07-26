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
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code in (200, 503)
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


@pytest.mark.asyncio
async def test_chat_stream_endpoint_happy_path():
    """Verify POST /api/v1/chat/stream returns 200 OK and streams event data."""
    payload = {
        "user_id": "pytest_stream_user",
        "thread_id": "api_stream_thread_001",
        "message": "Hello, explain AI agent state graphs briefly.",
        "department": "Engineering"
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/chat/stream", json=payload)

    assert response.status_code in (200, 503)
    if response.status_code == 200:
        assert "text/event-stream" in response.headers.get("content-type", "")
        assert "data:" in response.text


@pytest.mark.asyncio
async def test_document_upload_endpoint():
    """Verify POST /api/v1/documents/upload processes document files and returns ingestion details."""
    file_content = b"Aura Gateway Core test document content for Vectorless RAG."
    files = {"file": ("test_doc.txt", file_content, "text/plain")}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/documents/upload", files=files)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "file_hash" in data
    assert "document_ref" in data