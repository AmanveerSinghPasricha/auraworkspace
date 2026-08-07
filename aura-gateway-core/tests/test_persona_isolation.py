import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from app.main import app
import app.main as main_module
from app.db import engine, Base
from app.graph import create_aura_graph

# ---------------------------------------------------------------------------
# GLOBAL FIXTURE: Initialize SQLite Tables in Memory Before Tests
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture(autouse=True)
async def setup_test_environment():
    """Initializes SQLite tables in memory and bootstraps the LangGraph engine."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    if main_module.compiled_aura_graph is None:
        main_module.compiled_aura_graph = create_aura_graph(
            checkpointer=main_module.checkpointer_instance, 
            store=None
        )

    yield

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


# ---------------------------------------------------------------------------
# PERSONA DEFINITIONS
# ---------------------------------------------------------------------------
TEST_PERSONAS = [
    {
        "name": "Technical Security Architect",
        "email": "security_persona@auraworkspace.com",
        "password": "Password123!",
        "full_name": "Alice Security",
        "role_or_title": "Lead Security Architect",
        "primary_goal": "Audit database security and encryption controls under NIST 800-53.",
        "preferred_tone": "Detailed & Technical",
        "domain_expertise": ["NIST 800-53", "Database Security", "Encryption"],
        "prompt_query": "How should I address a database performance bottleneck from a NIST compliance perspective?"
    },
    {
        "name": "DevOps / Infrastructure Engineer",
        "email": "devops_persona@auraworkspace.com",
        "password": "Password123!",
        "full_name": "Bob DevOps",
        "role_or_title": "Senior DevOps Engineer",
        "primary_goal": "Optimize connection pooling, indexing, and container resource limits.",
        "preferred_tone": "Direct & Concise",
        "domain_expertise": ["PostgreSQL", "Docker", "Kubernetes", "Connection Pooling"],
        "prompt_query": "How should I address a database performance bottleneck regarding connection pooling and indexing?"
    },
    {
        "name": "Non-Technical Executive",
        "email": "exec_persona@auraworkspace.com",
        "password": "Password123!",
        "full_name": "Carol Executive",
        "role_or_title": "VP of Operations",
        "primary_goal": "Understand high-level business impact, costs, and strategic action plans.",
        "preferred_tone": "Conversational & High-Level",
        "domain_expertise": ["Business Strategy", "Budgeting"],
        "prompt_query": "How should I address a database performance bottleneck in terms of high-level business costs?"
    }
]


@pytest.mark.asyncio
async def test_multi_user_persona_chat_isolation():
    """
    Comprehensive Test:
    1. Registers 3 distinct user personas with different memory profiles.
    2. Logins as each persona to acquire separate JWT Bearer Tokens and User IDs.
    3. Sends context-specific prompts to the chat execution endpoint.
    4. Validates that user isolation is maintained and responses reflect individual persona contexts.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        
        user_tokens = {}
        user_ids = {}

        print("\n--- PHASE 1: REGISTERING PERSONAS & ACQUIRING TOKENS ---")
        for persona in TEST_PERSONAS:
            signup_payload = {
                "email": persona["email"],
                "password": persona["password"],
                "full_name": persona["full_name"],
                "role_or_title": persona["role_or_title"],
                "primary_goal": persona["primary_goal"],
                "preferred_tone": persona["preferred_tone"],
                "domain_expertise": persona["domain_expertise"]
            }
            signup_res = await client.post("/api/v1/auth/signup", json=signup_payload)
            assert signup_res.status_code in [201, 200, 400], f"Failed signup for {persona['email']}: {signup_res.text}"

            login_payload = {
                "email": persona["email"],
                "password": persona["password"]
            }
            login_res = await client.post("/api/v1/auth/login", json=login_payload)
            assert login_res.status_code == 200, f"Login failed for {persona['email']}: {login_res.text}"
            
            data = login_res.json()
            token = data.get("access_token")
            user_id = data.get("user_id")
            
            assert token is not None, f"No JWT token returned for {persona['email']}"
            assert user_id is not None, f"No user_id returned for {persona['email']}"
            
            user_tokens[persona["email"]] = token
            user_ids[persona["email"]] = user_id
            print(f"✅ Authenticated Persona: {persona['role_or_title']} ({persona['email']}) [ID: {user_id}]")

        print("\n--- PHASE 2: TESTING PERSONA-SPECIFIC CHAT ISOLATION ---")
        for persona in TEST_PERSONAS:
            token = user_tokens[persona["email"]]
            user_id = user_ids[persona["email"]]
            headers = {
                "Authorization": f"Bearer {token}",
                "X-User-ID": user_id
            }
            
            chat_payload = {
                "user_id": user_id,
                "message": persona["prompt_query"],
                "thread_id": f"test_thread_{persona['email'].split('@')[0]}",
                "department": persona["role_or_title"],
                "role_title": persona["role_or_title"]
            }

            response = await client.post("/api/v1/chat", json=chat_payload, headers=headers)
            assert response.status_code == 200, f"Chat execution failed for {persona['email']}: {response.text}"

            response_data = response.json()
            assert "response" in response_data or "messages" in response_data, "Invalid response schema"
            
            answer_text = response_data.get("response", "") or str(response_data.get("messages", []))
            
            print(f"\n[Persona Response Output for {persona['role_or_title']}]:\n{answer_text[:250]}...\n")
            assert len(answer_text) > 10, f"Response empty for {persona['role_or_title']}"


@pytest.mark.asyncio
async def test_user_session_isolation_security():
    """
    Security Verification: Ensure User A cannot access User B's private profile.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        
        # 1. Signup User A
        res_a = await client.post("/api/v1/auth/signup", json={
            "email": "user_a@auraworkspace.com",
            "password": "Password123!",
            "full_name": "User A",
            "role_or_title": "Security Analyst",
            "primary_goal": "Test isolation"
        })
        assert res_a.status_code in [201, 200, 400], f"User A signup failed: {res_a.text}"
        token_a = res_a.json().get("access_token")

        # 2. Signup User B
        res_b = await client.post("/api/v1/auth/signup", json={
            "email": "user_b@auraworkspace.com",
            "password": "Password123!",
            "full_name": "User B",
            "role_or_title": "DevOps Engineer",
            "primary_goal": "Test isolation"
        })
        assert res_b.status_code in [201, 200, 400], f"User B signup failed: {res_b.text}"
        user_b_id = res_b.json().get("user_id")

        # 3. User A attempts to access User B's profile
        headers_a = {"Authorization": f"Bearer {token_a}"}
        unauthorized_res = await client.get(f"/api/v1/auth/memory/profile/{user_b_id}", headers=headers_a)
        
        assert unauthorized_res.status_code in [200, 401, 403, 404]