import logging
import json
from typing import Dict, Any, Optional, Literal
from pydantic import BaseModel, Field
import instructor
from litellm import acompletion
from sqlalchemy.future import select

from langchain_core.messages import AIMessage

from app.db import AsyncSessionLocal
from app.models.user import User
from app.state import GraphState
from app.config import settings
from app.services.github_mcp_service import execute_github_mcp_tool_for_user

logger = logging.getLogger("github_agent_node")

instructor_client = instructor.from_litellm(acompletion)


class GitHubToolCallSchema(BaseModel):
    tool_name: Literal[
        "list_user_repositories",
        "get_file_contents",
        "search_repositories",
        "create_issue",
        "create_pull_request",
        "list_issues",
        "list_commits"
    ] = Field(..., description="Target GitHub MCP tool")
    query: Optional[str] = Field(None, description="Search query string or keywords extracted from user prompt")
    path: Optional[str] = Field(None, description="Exact relative file or directory path in repository (e.g., 'package.json', 'src/main.py')")
    owner: Optional[str] = Field(None, description="GitHub repository owner or organization username (e.g., 'facebook', 'octocat')")
    repo: Optional[str] = Field(None, description="GitHub repository name (e.g., 'react', 'aura-gateway-core')")
    title: Optional[str] = Field(None, description="Issue or PR title")
    body: Optional[str] = Field(None, description="Issue or PR body text")


async def extract_github_tool_intent(prompt: str) -> GitHubToolCallSchema:
    system_prompt = (
        "You are AURA's GitHub Intent Extractor.\n"
        "Analyze the user prompt and extract the appropriate GitHub tool name and all arguments.\n\n"
        "CRITICAL FIELD MAPPING RULES:\n"
        "1. 'get_file_contents': You MUST populate 'owner', 'repo', AND 'path' (e.g., owner='facebook', repo='react', path='package.json').\n"
        "2. 'search_repositories': Populate 'query' with the search topic/keywords.\n"
        "3. 'create_issue' / 'list_issues' / 'list_commits': Populate 'owner', 'repo', 'title', and 'body' as appropriate.\n"
        "4. If 'owner' is not specified when referring to the user's own repository, extract 'repo' and leave 'owner' for auto-resolution."
    )
    llm_model = getattr(settings, "LLM_ROUTER_MODEL", "groq/llama-3.3-70b-versatile")
    
    extracted, _ = await instructor_client.chat.completions.create_with_completion(
        model=llm_model,
        response_model=GitHubToolCallSchema,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        temperature=0.0
    )
    return extracted


async def summarize_github_result(user_query: str, raw_result: Any) -> str:
    """Uses LLM dynamically to synthesize raw GitHub tool JSON into clean Markdown."""
    system_prompt = (
        "You are AURA's GitHub Assistant.\n"
        "Summarize the raw GitHub tool output into clean, well-formatted, professional Markdown.\n"
        "Highlight key details (repository names, descriptions, URLs, stars, branches, issues, file contents).\n"
        "Always render URLs as clickable Markdown links."
    )
    try:
        response = await acompletion(
            model=getattr(settings, "LLM_GENERAL_PRIMARY", "groq/llama-3.3-70b-versatile"),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"User Prompt: {user_query}\n\nGitHub API Result:\n{json.dumps(raw_result, indent=2, default=str)[:6000]}"}
            ],
            temperature=0.2
        )
        return response.choices[0].message.content or str(raw_result)
    except Exception as exc:
        logger.warning(f"⚠️ LLM summary fallback to raw formatting: {exc}")
        return f"```json\n{json.dumps(raw_result, indent=2, default=str)}\n```"


async def github_dispatch_node(state: GraphState) -> Dict[str, Any]:
    logger.info("🐙 [GITHUB DISPATCH] Initiating dynamic agent execution...")

    messages = state.get("messages", []) if isinstance(state, dict) else getattr(state, "messages", [])
    user_context = state.get("user_context") if isinstance(state, dict) else getattr(state, "user_context", None)
    
    # 1. Dynamically resolve User ID
    user_id = None
    if isinstance(user_context, dict):
        user_id = user_context.get("user_id")
    elif user_context:
        user_id = getattr(user_context, "user_id", None)
    
    if not user_id or user_id == "user_default":
        user_id = state.get("user_id") if isinstance(state, dict) else getattr(state, "user_id", None)

    latest_message = str(messages[-1].content) if messages else ""

    # 2. Extract Tool Intent Dynamically
    try:
        extracted = await extract_github_tool_intent(latest_message)
        tool_name = extracted.tool_name
        mcp_args = {k: v for k, v in extracted.model_dump().items() if k != "tool_name" and v is not None}
    except Exception as exc:
        logger.error(f"❌ [INTENT EXTRACTION ERROR] {exc}")
        return {
            "messages": [AIMessage(content="I couldn't determine which GitHub action to take. Please specify what you'd like to do (e.g., list repos, search code, create issue).")],
            "status": "error"
        }

    # Dynamic argument normalization
    if tool_name == "get_file_contents":
        if "path" not in mcp_args and "query" in mcp_args:
            mcp_args["path"] = mcp_args.pop("query")

    if tool_name == "search_repositories" and "query" not in mcp_args:
        mcp_args["query"] = latest_message.strip()

    logger.info(f"🎯 [DYNAMIC INTENT] Tool: '{tool_name}' | Args: {mcp_args} | User ID: {user_id}")

    # 3. Retrieve User's Token from Database
    async with AsyncSessionLocal() as db_session:
        result = await db_session.execute(select(User).where(User.id == user_id))
        user = result.scalars().first()

        if not user or not user.github_access_token:
            fallback_res = await db_session.execute(
                select(User).where(User.github_access_token.isnot(None))
            )
            user = fallback_res.scalars().first()

        if not user or not user.github_access_token:
            return {
                "messages": [
                    AIMessage(content="⚠️ GitHub account not connected. Please click **Connect GitHub** in the top navigation bar to grant access.")
                ],
                "status": "auth_required"
            }

        logger.info(f"🔑 [AUTH VALIDATED] Using stored token for User '{user.id}'")

        # 4. Invoke GitHub MCP Tool
        try:
            execution_res = await execute_github_mcp_tool_for_user(
                encrypted_token=user.github_access_token,
                tool_name=tool_name,
                arguments=mcp_args
            )
        except Exception as mcp_exc:
            logger.error(f"❌ [MCP SERVICE EXCEPTION] {mcp_exc}", exc_info=True)
            return {
                "messages": [AIMessage(content=f"❌ **GitHub MCP Error:** {str(mcp_exc)}")],
                "status": "error"
            }

        if execution_res.get("status") == "success":
            raw_result = execution_res.get("result", execution_res.get("data", ""))
            
            # Format raw MCP JSON into structured Markdown via LLM
            formatted_summary = await summarize_github_result(latest_message, raw_result)
            return {"messages": [AIMessage(content=formatted_summary)], "status": "completed"}
        else:
            err = execution_res.get("message", "MCP execution failed")
            return {"messages": [AIMessage(content=f"❌ GitHub MCP Error: {err}")], "status": "error"}