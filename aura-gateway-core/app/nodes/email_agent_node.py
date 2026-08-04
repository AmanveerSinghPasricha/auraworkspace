"""
LangGraph Email Agent Node
==========================
1. Enforces mandatory Human-In-The-Loop (HITL) approval via interrupt().
2. Connects to the DB internally using AsyncSessionLocal (Compatible with LangGraph).
3. Executes email tools via Smithery AI Service.
"""

import logging
from typing import Dict, Any
from langchain_core.messages import AIMessage
from langgraph.types import interrupt
from sqlalchemy.future import select

from app.db import AsyncSessionLocal
from app.models.user import User
from app.state import GraphState
from app.services.smithery_service import execute_gmail_tool_for_user

logger = logging.getLogger("email_agent_node")

async def email_dispatch_node(state: GraphState) -> Dict[str, Any]:
    """
    Handles HITL approval and Smithery dispatch.
    """
    # 1. Extract inputs from state
    messages = state.get("messages", []) if isinstance(state, dict) else getattr(state, "messages", [])
    staged_payload = state.get("staged_action_payload", {}) if isinstance(state, dict) else getattr(state, "staged_action_payload", {})
    user_context = state.get("user_context") if isinstance(state, dict) else getattr(state, "user_context", None)
    user_id = getattr(user_context, "user_id", "user_default")

    body = staged_payload.get("resolved_query") or (str(messages[-1].content) if messages else "")
    recipient = staged_payload.get("recipient", "recipient@example.com")
    subject = staged_payload.get("subject", "Aura Workspace Notification")
    action_type = staged_payload.get("action_type", "send_email")

    # 2. TRIGGER HITL INTERRUPT
    # This pauses the graph execution and waits for a resume command from your frontend
    hitl_payload = {
        "action_type": action_type,
        "recipient": recipient,
        "subject": subject,
        "body": body,
        "message": "Human approval required prior to executing email action."
    }

    logger.info(f"⏸️ [HITL INTERRUPT] Halting graph execution for user: {user_id}")
    human_response = interrupt(hitl_payload)

    # 3. EVALUATE HUMAN RESUME RESPONSE
    if not isinstance(human_response, dict) or not human_response.get("approved", False):
        logger.warning(f"⛔ [HITL REJECTED] Dispatch rejected by user: {user_id}")
        return {"messages": [AIMessage(content="Email action rejected.")], "status": "cancelled"}

    # 4. LOOKUP USER DB RECORD (Using local session, NOT dependency injection)
    async with AsyncSessionLocal() as db_session:
        result = await db_session.execute(select(User).where(User.id == user_id))
        user = result.scalars().first()

        if not user or not user.smithery_connection_id:
            logger.error(f"❌ [EMAIL DISPATCH ERROR] User {user_id} missing Smithery connection.")
            return {"messages": [AIMessage(content="Error: Gmail account not connected.")], "status": "auth_required"}

        # 5. EXECUTE SMITHERY TOOL
        logger.info(f"🚀 [HITL APPROVED] Dispatching via Smithery for user: {user_id}")
        
        execution_res = await execute_gmail_tool_for_user(
            connection_id=user.smithery_connection_id,
            tool_name=action_type,
            payload={"to": recipient, "subject": subject, "body": body}
        )

        if execution_res.get("status") == "success":
            return {
                "messages": [AIMessage(content=f"✅ Successfully sent email to `{recipient}`.")],
                "status": "completed"
            }
        else:
            return {
                "messages": [AIMessage(content=f"❌ Failed: {execution_res.get('message')}")],
                "status": "error"
            }