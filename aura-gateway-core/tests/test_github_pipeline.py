import os
import pytest
import asyncio
import logging
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from langchain_core.messages import HumanMessage

# 1. Force environment variable and sanitize SSL parameters for asyncpg
NEON_RAW_URL = "postgresql+asyncpg://neondb_owner:npg_DEZh5jnwQag7@ep-super-frog-azqnoh50.c-3.ap-southeast-1.aws.neon.tech/neondb"
os.environ["DATABASE_URL"] = NEON_RAW_URL

import ssl
ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

# Create a dedicated AsyncEngine re-bound specifically to live Neon Postgres
neon_engine = create_async_engine(
    NEON_RAW_URL,
    connect_args={"ssl": ssl_ctx},
    echo=False
)
TestAsyncSession = async_sessionmaker(neon_engine, class_=AsyncSession, expire_on_commit=False)

# Monkeypatch app.db's AsyncSessionLocal so the nodes (like github_dispatch_node) use Neon DB instead of SQLite
import app.db
app.db.AsyncSessionLocal = TestAsyncSession

from app.models.user import User
from app.nodes.github_agent_node import (
    github_dispatch_node,
    extract_github_tool_intent
)
from app.services.github_mcp_service import execute_github_mcp_tool_for_user
from app.graph import create_aura_graph

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("test_github_pipeline")

TEST_USER_ID = "02b7cfb6-f0b2-4d6e-a87b-0b85d4af5fb6"


@pytest.mark.asyncio
async def test_step_1_db_token():
    """Step 1: Verify token persistence in Neon PostgreSQL using standard DB session."""
    print("\n--- STEP 1: DB TOKEN CHECK ---")
    async with TestAsyncSession() as session:
        result = await session.execute(select(User).where(User.id == TEST_USER_ID))
        user = result.scalars().first()

        if not user or not user.github_access_token:
            fallback_res = await session.execute(
                select(User).where(User.github_access_token.isnot(None))
            )
            user = fallback_res.scalars().first()

        assert user is not None, "❌ No user found in Neon DB. Connect GitHub via frontend first."
        assert user.github_access_token is not None, f"❌ User '{user.id}' exists but has no GitHub token saved."

        print(f"✅ SUCCESS: Found User '{user.id}' with active GitHub access token.")


@pytest.mark.asyncio
async def test_step_2_intent_extraction():
    """Step 2: Verify zero-hardcode LLM parameter extraction across different prompt types."""
    print("\n--- STEP 2: INTENT EXTRACTION UNIT TEST ---")
    
    # Test 1: Search Intent
    search_prompt = "Search for public repositories owned by 'facebook' that are related to 'react-native'"
    intent_1 = await extract_github_tool_intent(search_prompt)
    assert intent_1.tool_name == "search_repositories"
    assert intent_1.owner == "facebook"
    assert "react-native" in (intent_1.query or "")
    print(f"✅ Search Intent Extracted: Tool={intent_1.tool_name}, Owner={intent_1.owner}, Query={intent_1.query}")

    # Test 2: File Reading Intent
    file_prompt = "Get the content of file package.json from the repository facebook/react"
    intent_2 = await extract_github_tool_intent(file_prompt)
    assert intent_2.tool_name == "get_file_contents"
    assert intent_2.owner == "facebook"
    assert intent_2.repo == "react"
    assert intent_2.path == "package.json"
    print(f"✅ File Reading Intent Extracted: Tool={intent_2.tool_name}, Path={intent_2.path}")


@pytest.mark.asyncio
async def test_step_3_mcp_direct_execution():
    """Step 3: Test execute_github_mcp_tool_for_user STDIO invocation directly."""
    print("\n--- STEP 3: MCP DIRECT EXECUTION TEST ---")
    
    async with TestAsyncSession() as session:
        result = await session.execute(
            select(User).where(User.github_access_token.isnot(None))
        )
        user = result.scalars().first()
        assert user is not None, "No active GitHub token available in database."

        # Execute search_repositories via MCP runner
        res = await execute_github_mcp_tool_for_user(
            encrypted_token=user.github_access_token,
            tool_name="search_repositories",
            arguments={"query": "python", "owner": "facebook"}
        )

        assert res.get("status") == "success", f"MCP Execution failed: {res.get('message')}"
        print(f"✅ MCP Direct Call Succeeded: Result payload keys = {list(res.keys())}")


@pytest.mark.asyncio
async def test_step_4_full_langgraph_flow():
    """Step 4: End-to-End LangGraph execution test with LLM synthesis output."""
    print("\n--- STEP 4: FULL LANGGRAPH END-TO-END FLOW ---")
    graph = create_aura_graph()

    initial_state = {
        "messages": [HumanMessage(content="Get the content of file package.json from the repository facebook/react")],
        "user_id": TEST_USER_ID,
        "user_context": {"user_id": TEST_USER_ID},
        "staged_action_payload": {}
    }

    final_state = await graph.ainvoke(
        initial_state,
        config={"configurable": {"thread_id": "test_thread_pipeline_001"}}
    )

    messages = final_state.get("messages", [])
    assert len(messages) > 0, "Graph failed to yield output message."

    last_msg = str(messages[-1].content)
    print(f"✅ GRAPH EXECUTION COMPLETE!")
    print(f"Final Message Output Preview:\n{last_msg[:300]}...")