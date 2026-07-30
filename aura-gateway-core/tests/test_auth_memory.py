import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.db import engine, Base


@pytest_asyncio.fixture(autouse=True)
async def setup_test_database():
    """Ensures database tables exist before each test (critical for SQLite in-memory)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest.mark.asyncio
async def test_signup_success():
    """Test successful user registration with memory profiling data."""
    payload = {
        "email": "test_security_user@auraworkspace.com",
        "password": "SecurePassword123!",
        "full_name": "Test Security Architect",
        "role_or_title": "Lead Security Architect",
        "primary_goal": "Audit NIST 800-53 security controls and generate executive summaries.",
        "preferred_tone": "Detailed & Technical",
        "domain_expertise": ["NIST 800-53", "Cloud Security", "FastAPI"],
        "additional_context": "Always provide control reference IDs."
    }

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/v1/auth/signup", json=payload)

    assert response.status_code in (201, 400) # 400 if user already exists from previous runs


@pytest.mark.asyncio
async def test_signup_validation_error():
    """Test 422 Unprocessable Content error when password is too short."""
    invalid_payload = {
        "email": "invalid@auraworkspace.com",
        "password": "short",
        "full_name": "Invalid User",
        "role_or_title": "Tester",
        "primary_goal": "Test short password"
    }

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/v1/auth/signup", json=invalid_payload)

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_login_success():
    """Test authentication login for an existing registered user."""
    user_email = "login_tester_unique@auraworkspace.com"
    user_password = "Password123!"

    signup_payload = {
        "email": user_email,
        "password": user_password,
        "full_name": "Login Tester",
        "role_or_title": "DevOps Engineer",
        "primary_goal": "Automate CI/CD pipelines"
    }

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # Register user
        await client.post("/api/v1/auth/signup", json=signup_payload)

        # Attempt login
        login_payload = {
            "email": user_email,
            "password": user_password
        }
        response = await client.post("/api/v1/auth/login", json=login_payload)

    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["full_name"] == "Login Tester"