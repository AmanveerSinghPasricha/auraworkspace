import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.future import select

from app.main import app
from app.db import Base, get_db
from app.models.user import User
from app.core.security import verify_password

# SQLite in-memory database setup for isolated fast tests
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="function")
async def test_db_session():
    """Sets up an in-memory database schema before each test and cleans up after."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    TestingSessionLocal = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with TestingSessionLocal() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def client(test_db_session):
    """FastAPI TestClient overriding get_db dependency with in-memory session."""
    async def _override_get_db():
        yield test_db_session

    app.dependency_overrides[get_db] = _override_get_db
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client
        
    app.dependency_overrides.clear()


# =====================================================================
# PHASE 4 TEST SUITE: AUTH & LONG-TERM MEMORY INGESTION
# =====================================================================

@pytest.mark.asyncio
async def test_signup_creates_user_with_memory_profile(client: AsyncClient, test_db_session: AsyncSession):
    """Test 1: Verify user registration persists credentials AND long-term memory traits."""
    signup_payload = {
        "email": "analyst.jane@example.com",
        "password": "SecurePassword123!",
        "full_name": "Jane Doe",
        "role_or_title": "Lead Security Analyst",
        "primary_goal": "Audit NIST 800-53 compliance controls.",
        "preferred_tone": "Detailed & Technical",
        "domain_expertise": ["NIST 800-53", "Cloud Security", "FastAPI"],
        "additional_context": "Always provide citations and highlight critical risk factors."
    }

    response = await client.post("/api/v1/auth/signup", json=signup_payload)
    
    assert response.status_code == 201
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["full_name"] == "Jane Doe"
    assert data["user_id"].startswith("usr_")

    # Verify Database Persistence
    result = await test_db_session.execute(select(User).where(User.email == "analyst.jane@example.com"))
    db_user = result.scalars().first()

    assert db_user is not None
    assert db_user.full_name == "Jane Doe"
    assert verify_password("SecurePassword123!", db_user.hashed_password)
    assert db_user.role_or_title == "Lead Security Analyst"
    assert db_user.preferred_tone == "Detailed & Technical"
    assert "NIST 800-53" in db_user.domain_expertise


@pytest.mark.asyncio
async def test_signup_duplicate_email_fails(client: AsyncClient):
    """Test 2: Ensure duplicate email registration is rejected with 400 Bad Request."""
    payload = {
        "email": "duplicate@example.com",
        "password": "Password123!",
        "full_name": "John Smith",
        "role_or_title": "Software Engineer",
        "primary_goal": "Code generation",
        "preferred_tone": "Direct & Concise",
        "domain_expertise": ["Python"]
    }

    # First registration
    res1 = await client.post("/api/v1/auth/signup", json=payload)
    assert res1.status_code == 201

    # Duplicate registration attempt
    res2 = await client.post("/api/v1/auth/signup", json=payload)
    assert res2.status_code == 400
    assert "already exists" in res2.json()["detail"]


@pytest.mark.asyncio
async def test_login_success_and_failure(client: AsyncClient):
    """Test 3: Verify authentication with valid credentials and failure with wrong password."""
    # 1. Register User
    signup_payload = {
        "email": "dev.alex@example.com",
        "password": "CorrectPassword123!",
        "full_name": "Alex Mercer",
        "role_or_title": "DevOps Engineer",
        "primary_goal": "Automate deployment pipelines.",
        "preferred_tone": "Direct & Concise",
        "domain_expertise": ["Docker", "Kubernetes"]
    }
    await client.post("/api/v1/auth/signup", json=signup_payload)

    # 2. Test Invalid Login
    invalid_login = {
        "email": "dev.alex@example.com",
        "password": "WrongPassword!"
    }
    bad_res = await client.post("/api/v1/auth/login", json=invalid_login)
    assert bad_res.status_code == 401
    assert "Invalid credentials" in bad_res.json()["detail"]

    # 3. Test Valid Login
    valid_login = {
        "email": "dev.alex@example.com",
        "password": "CorrectPassword123!"
    }
    good_res = await client.post("/api/v1/auth/login", json=valid_login)
    assert good_res.status_code == 200
    assert "access_token" in good_res.json()


@pytest.mark.asyncio
async def test_get_user_memory_profile_endpoint(client: AsyncClient):
    """Test 4: Verify retrieval of the formatted memory profile used by LLM chat nodes."""
    # 1. Register User
    signup_payload = {
        "email": "profile.user@example.com",
        "password": "Password123!",
        "full_name": "Sarah Connor",
        "role_or_title": "Security Specialist",
        "primary_goal": "Assess AI security risks.",
        "preferred_tone": "Conversational",
        "domain_expertise": ["AI Safety", "Risk Management"],
        "additional_context": "User prefers concise executive summaries."
    }
    signup_res = await client.post("/api/v1/auth/signup", json=signup_payload)
    user_id = signup_res.json()["user_id"]

    # 2. Query Memory Profile Endpoint
    profile_res = await client.get(f"/api/v1/auth/memory/profile/{user_id}")
    assert profile_res.status_code == 200
    profile_data = profile_res.json()

    assert profile_data["user_id"] == user_id
    assert profile_data["role_or_title"] == "Security Specialist"
    
    # Check that formatted system prompt summary string contains key memory fields
    summary = profile_data["profile_summary"]
    assert "User Name: Sarah Connor" in summary
    assert "Role/Title: Security Specialist" in summary
    assert "Communication Tone: Conversational" in summary
    assert "AI Safety, Risk Management" in summary
    assert "User prefers concise executive summaries." in summary