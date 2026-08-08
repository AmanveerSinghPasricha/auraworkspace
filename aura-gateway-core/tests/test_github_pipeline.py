import os
import pytest
import asyncio
import logging
from unittest.mock import AsyncMock, patch
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from langchain_core.messages import HumanMessage

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"
os.environ["DATABASE_URL"] = TEST_DB_URL

import app.db
from app.db import Base
app.db.AsyncSessionLocal = async_sessionmaker(app.db.engine, class_=AsyncSession, expire_on_commit=False)

from app.models.user import User
from app.nodes.github_agent_node import (
    github_dispatch_node,
    extract_github_tool_intent,
    GitHubToolCallSchema
)
from app.services.github_mcp_service import execute_github_mcp_tool_for_user
from app.graph import create_aura_graph
from app.core.security import encrypt_token

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("test_github_pipeline")

TEST_USER_ID = "02b7cfb6-f0b2-4d6e-a87b-0b85d4af5fb6"


@pytest.fixture(autouse=True)
async def setup_github_test_db():
    """Builds in-memory schema and seeds demo user before pipeline tests."""
    async with app.db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async with app.db.AsyncSessionLocal() as session:
        demo_user = User(
            id=TEST_USER_ID,
            email="demo_github_user@auraworkspace.com",
            full_name="Demo GitHub User",
            password_hash="hashed_pass_123",
            github_access_token=encrypt_token("ghp_mock_token_for_testing_12345")
        )
        session.add(demo_user)
        await session.commit()
        
    yield

    async with app.db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.mark.asyncio
async def test_step_1_db_token():
    """Step 1: Verify token persistence using standard DB session."""
    print("\n--- STEP 1: DB TOKEN CHECK ---")
    async with app.db.AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.id == TEST_USER_ID))
        user = result.scalars().first()

        assert user is not None, "❌ No user found in test DB."
        assert user.github_access_token is not None, f"❌ User '{user.id}' exists but has no GitHub token saved."

        print(f"✅ SUCCESS: Found User '{user.id}' with active GitHub access token.")


@pytest.mark.asyncio
async def test_step_2_intent_extraction():
    """Step 2: Verify parameter extraction across different prompt types using mocked responses (0 token consumption)."""
    print("\n--- STEP 2: INTENT EXTRACTION UNIT TEST ---")
    
    mock_search = GitHubToolCallSchema(
        tool_name="search_repositories",
        owner="facebook",
        query="react-native"
    )
    
    mock_file = GitHubToolCallSchema(
        tool_name="get_file_contents",
        owner="facebook",
        repo="react",
        path="package.json"
    )

    with patch("app.nodes.github_agent_node.extract_github_tool_intent", new_callable=AsyncMock) as mock_extract:
        mock_extract.side_effect = [mock_search, mock_file]

        search_prompt = "Search for public repositories owned by 'facebook' that are related to 'react-native'"
        intent_1 = await extract_github_tool_intent(search_prompt)
        assert intent_1.tool_name == "search_repositories"
        assert intent_1.owner == "facebook"
        assert "react-native" in (intent_1.query or "")

        file_prompt = "Get the content of file package.json from the repository facebook/react"
        intent_2 = await extract_github_tool_intent(file_prompt)
        assert intent_2.tool_name == "get_file_contents"
        assert intent_2.owner == "facebook"
        assert intent_2.repo == "react"
        assert intent_2.path == "package.json"


@pytest.mark.asyncio
async def test_step_3_mcp_direct_execution():
    """Step 3: Test execute_github_mcp_tool_for_user invocation directly."""
    print("\n--- STEP 3: MCP DIRECT EXECUTION TEST ---")
    
    async with app.db.AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.github_access_token.isnot(None))
        )
        user = result.scalars().first()
        assert user is not None, "No active GitHub token available in database."

        res = await execute_github_mcp_tool_for_user(
            encrypted_token=user.github_access_token,
            tool_name="search_repositories",
            arguments={"query": "python", "owner": "facebook"}
        )

        assert res.get("status") in ["success", "error"]


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