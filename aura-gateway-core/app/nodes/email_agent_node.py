"""
Aura Gateway Core - Email Extraction & Dispatch Agent Node
==========================================================
1. Uses `instructor` to extract structured email parameters (recipient, subject, body, action_type).
2. Enforces mandatory Human-In-The-Loop (HITL) approval via `interrupt()`.
3. Resolves user's encrypted Google OAuth refresh token dynamically from Postgres DB.
4. Dispatches direct email via native Gmail API (`send_direct_email`) upon approval.
"""

import logging
from typing import Dict, Any, Literal
from pydantic import BaseModel, Field
import instructor
from litellm import acompletion
from langchain_core.messages import AIMessage
from langgraph.types import interrupt
from sqlalchemy.future import select

from app.state import GraphState
from app.config import settings
from app.db import AsyncSessionLocal
from app.models.user import User
from app.services.email_service import send_direct_email

logger = logging.getLogger("email_agent_node")

# Initialize Instructor patched client for LiteLLM
instructor_client = instructor.from_litellm(acompletion)


# =====================================================================
# 1. PYDANTIC OUTPUT SCHEMA CONTRACT
# =====================================================================
class EmailIntentSchema(BaseModel):
    action_type: Literal["send_email", "draft_email"] = Field(
        default="send_email",
        description="Target action type ('send_email' or 'draft_email')."
    )
    recipient: str = Field(
        ..., 
        description="Target email address or name/identifier if address is missing."
    )
    subject: str = Field(
        ..., 
        description="Concise, objective subject line (3-8 words)."
    )
    body: str = Field(
        ..., 
        description="Professional, well-formatted email body text."
    )
    validation_notes: str = Field(
        default="", 
        description="Any extraction warnings or missing detail flags."
    )


# =====================================================================
# 2. SYSTEM PROMPT DEFINITION
# =====================================================================
SYSTEM_PROMPT = """You are the Specialized Email Intent & Synthesis Agent inside Project Aura. Your task is to process natural language user requests, extract target email dispatch parameters, and compile a clean, professional email draft.

### OBJECTIVE
Analyze the incoming conversation history and user prompt to construct a structured EmailIntentSchema object. Do NOT execute the email dispatch yourself; your output will be staged for Human-in-The-Loop (HITL) confirmation.

---
### EXTRACTION & SYNTHESIS RULES
1. RECIPIENT IDENTIFICATION:
   - Extract explicitly stated email addresses (e.g., "john.doe@example.com").
   - If a person's name or title is given without an explicit email (e.g., "Send an email to John in Operations"), set `recipient` to the name/identifier provided or flag missing details in `validation_notes`.

2. SUBJECT LINE GENERATION:
   - Generate a concise, objective, and contextually accurate subject line (3 to 8 words).
   - Never leave the subject line empty. Avoid generic subjects like "Email" or "Hello". Use actionable summaries (e.g., "Operational Audit Summary - Q3 Reconciliation").

3. BODY COMPOSITION:
   - Write a professional, clear, and well-formatted email body using standard business grammar.
   - If the user prompt references previous context, data frames, or Vectorless RAG extractions from the thread, synthesize those details accurately into the message.
   - Respect user formatting preferences specified in user_context.

4. ACTION TYPE CLASSIFICATION:
   - Classify `action_type` as:
     * `send_email`: User wants to send an email immediately (triggers the HITL confirmation gate).
     * `draft_email`: User explicitly requests a draft or review only.

5. SAFETY & SANITIZATION:
   - Do NOT process or embed internal corporate secrets, system access keys, or raw passwords into the output email body.
   - Redact sensitive credentials using `[REDACTED_CREDENTIAL]` tokens if present in the context.
"""


# =====================================================================
# 3. LANGGRAPH NODE EXECUTION
# =====================================================================
async def email_dispatch_node(state: GraphState) -> Dict[str, Any]:
    """
    Extracts structured email parameters, triggers HITL interrupt for human approval,
    resolves user's Google OAuth refresh token, and dispatches email upon resume.
    """
    logger.info("📧 [EMAIL AGENT] Extracting email intent and parameters...")

    # Safely extract state variables
    messages = state.get("messages", []) if isinstance(state, dict) else getattr(state, "messages", [])
    staged_payload = state.get("staged_action_payload", {}) if isinstance(state, dict) else getattr(state, "staged_action_payload", {})
    user_context = state.get("user_context") if isinstance(state, dict) else getattr(state, "user_context", None)
    
    # 1. RESOLVE USER ID DYNAMICALLY WITH DEFAULT FALLBACK
    raw_user_id = state.get("user_id") if isinstance(state, dict) else getattr(state, "user_id", None)
    if not raw_user_id or str(raw_user_id).lower() in ["none", "null", "undefined", "user_default"]:
        resolved_user_id = "02b7cfb6-f0b2-4d6e-a87b-0b85d4af5fb6"
    else:
        resolved_user_id = str(raw_user_id)

    latest_user_prompt = str(messages[-1].content) if messages else ""

    # Format history context window (last 5 messages)
    recent_history = []
    if messages:
        for msg in messages[-5:]:
            role = getattr(msg, "type", "user")
            content = getattr(msg, "content", str(msg))
            recent_history.append(f"{role.upper()}: {content}")
    history_str = "\n".join(recent_history)

    llm_model = getattr(settings, "LLM_ROUTER_MODEL", "groq/llama-3.3-70b-versatile")
    fallback_model = getattr(settings, "LLM_ROUTER_FALLBACK", "groq/llama-3.1-8b-instant")

    # 2. EXTRACT STRUCTURED INTENT VIA INSTRUCTOR
    try:
        extracted_intent, _ = await instructor_client.chat.completions.create_with_completion(
            model=llm_model,
            response_model=EmailIntentSchema,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"User Context: {user_context}\n\nRecent Conversation:\n{history_str}\n\nUser Prompt: {latest_user_prompt}"}
            ],
            temperature=0.1,
            fallbacks=[fallback_model],
            max_retries=2
        )
    except Exception as exc:
        logger.error(f"❌ [EMAIL EXTRACTION ERROR] Failed to extract schema: {exc}", exc_info=True)
        return {
            "messages": [AIMessage(content="I couldn't extract the recipient or email body clearly. Please specify who you want to email and the message details.")],
            "validation_errors": [str(exc)]
        }

    # 3. STAGE ACTION PAYLOAD
    staged_action = {
        "action_type": extracted_intent.action_type,
        "recipient": extracted_intent.recipient,
        "subject": extracted_intent.subject,
        "body": extracted_intent.body,
        "validation_notes": extracted_intent.validation_notes
    }

    logger.info(f"🎯 [EMAIL STAGED] To: {staged_action['recipient']} | Subject: '{staged_action['subject']}'")

    # 4. TRIGGER HITL INTERRUPT GATE
    hitl_payload = {
        "action_type": staged_action["action_type"],
        "recipient": staged_action["recipient"],
        "subject": staged_action["subject"],
        "body": staged_action["body"],
        "message": "Human authorization required prior to dispatching email."
    }

    logger.info("⏸️ [HITL INTERRUPT] Halting graph execution for user confirmation...")
    human_response = interrupt(hitl_payload)

    # 5. EVALUATE RESUME RESPONSE FROM FRONTEND
    if not isinstance(human_response, dict) or not human_response.get("approved", False):
        logger.warning("⛔ [HITL REJECTED] Dispatch cancelled by user.")
        return {
            "messages": [AIMessage(content="Email action was cancelled by user.")],
            "staged_action_payload": staged_action,
            "validation_errors": []
        }

    # 6. DYNAMICALLY FETCH ENCRYPTED REFRESH TOKEN FROM DB BY USER ID
    logger.info(f"🚀 [HITL APPROVED] Resolving OAuth refresh token for user '{resolved_user_id}'...")
    encrypted_refresh_token = None

    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(select(User).where(User.id == resolved_user_id))
            user = result.scalars().first()

            if user and user.google_refresh_token:
                encrypted_refresh_token = user.google_refresh_token
                logger.info(f"✅ [OAUTH TOKEN LOADED] Token retrieved for user: {user.email}")
            else:
                logger.error(f"❌ [OAUTH ERROR] No google_refresh_token found for user_id: '{resolved_user_id}'")
        except Exception as db_exc:
            logger.error(f"❌ [DATABASE ERROR] Failed to fetch user refresh token: {db_exc}", exc_info=True)

    # 7. EXECUTE DIRECT NATIVE EMAIL DISPATCH VIA GMAIL REST API
    logger.info(f"📬 Dispatching email to '{staged_action['recipient']}' via Gmail REST API...")
    
    dispatch_res = await send_direct_email(
        recipient=staged_action["recipient"],
        subject=staged_action["subject"],
        body=staged_action["body"],
        encrypted_refresh_token=encrypted_refresh_token
    )

    if dispatch_res.get("status") == "success":
        return {
            "messages": [AIMessage(content=f"✅ Successfully sent email to `{staged_action['recipient']}`.")],
            "staged_action_payload": staged_action,
            "validation_errors": []
        }
    else:
        err = dispatch_res.get("message", "Unknown email dispatch failure.")
        return {
            "messages": [AIMessage(content=f"❌ Failed to send email: {err}")],
            "staged_action_payload": staged_action,
            "validation_errors": [err]
        }