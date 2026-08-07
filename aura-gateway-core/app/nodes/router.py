"""
Aura Gateway Core - Production Supervisor Intent Router Node
============================================================
Classifies user intent dynamically into active graph execution routes:
- GENERAL_AGENT: Open-ended conversation, general chat, or coding help
- RAG_ENGINE: Knowledge base retrieval & document-grounded queries
- EXTRACTOR: Structured matrix/JSON schema extraction requests
- EMAIL_AGENT: Dispatching, drafting, sending emails, or contacting recipients
- GITHUB_AGENT: Managing GitHub repos, issues, pull requests, commits, or code search
"""

import logging
from typing import Dict, Any, Literal
from pydantic import BaseModel, Field
import instructor
from litellm import acompletion
from langchain_core.messages import AIMessage

from app.config import settings
from app.state import GraphState

logger = logging.getLogger("router_node")

# Initialize Instructor patched client for LiteLLM
instructor_client = instructor.from_litellm(acompletion)


class IntentClassification(BaseModel):
    """Pydantic model for strict router intent output from LLM."""
    active_route: Literal["GENERAL_AGENT", "RAG_ENGINE", "EXTRACTOR", "EMAIL_AGENT", "GITHUB_AGENT"] = Field(
        ...,
        description="The assigned execution branch. Allowed values: 'GENERAL_AGENT', 'RAG_ENGINE', 'EXTRACTOR', 'EMAIL_AGENT', or 'GITHUB_AGENT'."
    )
    confidence_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence score for route assignment between 0.0 and 1.0."
    )
    reasoning: str = Field(
        ...,
        description="Brief justification for why this route was selected."
    )


async def supervisor_router_node(state: GraphState) -> Dict[str, Any]:
    """
    LangGraph node that uses Instructor to classify intent and set active_route in state.
    Evaluates both conversation history and active document attachment context.
    """
    logger.info("🔀 [LLM GATEWAY ROUTER] Classifying query intent via Pure LLM Engine...")

    # Extract messages and staged payload
    messages = state.get("messages", []) if isinstance(state, dict) else getattr(state, "messages", [])
    staged_payload = state.get("staged_action_payload", {}) if isinstance(state, dict) else getattr(state, "staged_action_payload", {})
    router_state = state.get("router_state", {}) if isinstance(state, dict) else getattr(state, "router_state", {})

    # Extract latest query text
    user_query = ""
    if staged_payload and staged_payload.get("resolved_query"):
        user_query = staged_payload["resolved_query"]
    elif messages:
        user_query = str(messages[-1].content)

    if not user_query:
        logger.warning("⚠️ [ROUTER WARNING] Empty query provided. Routing to GENERAL_AGENT.")
        return {
            "router_state": {
                "active_route": "GENERAL_AGENT",
                "confidence": 1.0,
                "reasoning": "Default fallback for empty query."
            },
            "validation_errors": []
        }

    # Extract conversation context (last 3 messages)
    recent_history = []
    if messages:
        for msg in messages[-3:]:
            role = getattr(msg, "type", "user")
            content = getattr(msg, "content", str(msg))
            recent_history.append(f"{role.upper()}: {content}")
    history_str = "\n".join(recent_history) if recent_history else f"USER: {user_query}"

    # Check active document context
    doc_ref = (
        staged_payload.get("document_ref") 
        or (router_state.get("last_document_ref") if isinstance(router_state, dict) else getattr(router_state, "last_document_ref", None))
    )
    has_active_doc = bool(doc_ref)

    system_prompt = (
        "You are Aura Workspace's Central Intent Supervisor.\n"
        "Your task is to analyze the conversation context and select the exact active route:\n\n"
        "1. 'GITHUB_AGENT': Select if the user wants to interact with GitHub (list repositories, create issues, search code, check pull requests, view commit history, or inspect user repos).\n"
        "2. 'EMAIL_AGENT': Select if the user wants to communicate, contact, notify, draft, send an email, or deliver a message to any recipient (including sanitized tokens like <EMAIL_ADDRESS>).\n"
        "3. 'RAG_ENGINE': Select if the query asks about document content, rules, NIST controls, policies, PDF technical specs, or if the user is answering a previous document disambiguation question.\n"
        "4. 'EXTRACTOR': Select ONLY if the user explicitly requests to parse, transform, or extract unstructured input directly into a structured table, JSON schema, or matrix format.\n"
        "5. 'GENERAL_AGENT': Select for casual greetings, general knowledge, standard conversation, or non-document tasks.\n\n"
        f"Active Workspace Context: Document Currently Attached = {has_active_doc}\n"
        "Outputs MUST match one of these exact route names: GENERAL_AGENT, RAG_ENGINE, EXTRACTOR, EMAIL_AGENT, or GITHUB_AGENT."
    )

    try:
        router_model = getattr(settings, "LLM_ROUTER_MODEL", "groq/llama-3.3-70b-versatile")
        fallback_model = getattr(settings, "LLM_ROUTER_FALLBACK", "groq/llama-3.1-8b-instant")

        classification, _ = await instructor_client.chat.completions.create_with_completion(
            model=router_model,
            response_model=IntentClassification,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Conversation History:\n{history_str}"}
            ],
            temperature=0.0,
            fallbacks=[fallback_model],
            max_retries=2,
        )

        route_upper = classification.active_route.upper()
        allowed_routes = ["GENERAL_AGENT", "RAG_ENGINE", "EXTRACTOR", "EMAIL_AGENT", "GITHUB_AGENT"]
        if route_upper not in allowed_routes:
            route_upper = "RAG_ENGINE" if has_active_doc else "GENERAL_AGENT"

        logger.info(f"🎯 [ROUTER DECISION] Route: '{route_upper}' | Confidence: {classification.confidence_score} | Reason: {classification.reasoning}")

        return {
            "router_state": {
                "active_route": route_upper,
                "confidence": classification.confidence_score,
                "reasoning": classification.reasoning
            },
            "validation_errors": []
        }

    except Exception as exc:
        logger.error(f"❌ [LLM ROUTER ERROR] Intent classification failed: {exc}")
        
        # Safe state-aware fallback
        fallback_route = "RAG_ENGINE" if has_active_doc else "GENERAL_AGENT"
        return {
            "router_state": {
                "active_route": fallback_route,
                "confidence": 0.5,
                "reasoning": f"Fallback triggered due to router error: {str(exc)}"
            },
            "validation_errors": [f"Gateway Fallback Triggered: {str(exc)}"]
        }