"""
Aura Gateway Core - Supervisor Intent Router Node
==================================================
Classifies user intent into active graph execution routes:
- GENERAL_AGENT: Open-ended conversation or general queries
- RAG_TREE: Knowledge base retrieval queries
- EXTRACTOR: Structured matrix data extraction requests
"""

import logging
from typing import Dict, Any, Optional
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
    active_route: str = Field(
        ...,
        description="The assigned execution branch. Allowed values: 'GENERAL_AGENT', 'RAG_TREE', or 'EXTRACTOR'."
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
    """
    logger.info("?? [LLM GATEWAY ROUTER] Classifying query intent via Pure LLM Engine...")

    # Extract query text from messages or staged action payload
    user_query = ""
    if state.staged_action_payload and state.staged_action_payload.get("resolved_query"):
        user_query = state.staged_action_payload["resolved_query"]
    elif state.messages:
        user_query = str(state.messages[-1].content)

    if not user_query:
        logger.warning("?? [ROUTER WARNING] Empty query provided. Routing to GENERAL_AGENT.")
        return {
            "router_state": {
                "active_route": "GENERAL_AGENT",
                "confidence": 1.0,
                "reasoning": "Default fallback for empty query."
            },
            "validation_errors": []
        }

    system_prompt = (
        "You are Aura Workspace's Intent Classification Supervisor.\n"
        "Your task is to analyze the user's prompt and assign the most appropriate execution route:\n\n"
        "1. 'EXTRACTOR': Select if the user wants to extract structured data, tables, key-value pairs, metrics, or parse figures from a document/text into JSON/matrix format.\n"
        "2. 'RAG_TREE': Select if the user is asking questions about company documents, policies, internal search, or knowledge base context.\n"
        "3. 'GENERAL_AGENT': Select for open-ended conversation, coding help, general assistance, or standard Q&A.\n\n"
        "Outputs MUST match one of these exact route names: GENERAL_AGENT, RAG_TREE, or EXTRACTOR."
    )

    try:
        # Use settings.LLM_ROUTER_MODEL (groq/llama-3.1-8b-instant)
        router_model = getattr(settings, "LLM_ROUTER_MODEL", "groq/llama-3.1-8b-instant")

        classification, raw_completion = await instructor_client.chat.completions.create_with_completion(
            model=router_model,
            response_model=IntentClassification,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_query}
            ],
            temperature=0.0,
            max_retries=2,
        )

        route_upper = classification.active_route.upper()
        if route_upper not in ["GENERAL_AGENT", "RAG_TREE", "EXTRACTOR"]:
            route_upper = "GENERAL_AGENT"

        logger.info(f"?? [ROUTER DECISION] Route: '{route_upper}' | Confidence: {classification.confidence_score} | Reason: {classification.reasoning}")

        return {
            "router_state": {
                "active_route": route_upper,
                "confidence": classification.confidence_score,
                "reasoning": classification.reasoning
            },
            "validation_errors": []
        }

    except Exception as exc:
        logger.error(f"? [LLM ROUTER ERROR] Intent classification failed: {exc}")
        
        # Safe fallback to GENERAL_AGENT on model failure
        return {
            "router_state": {
                "active_route": "GENERAL_AGENT",
                "confidence": 0.5,
                "reasoning": f"Fallback triggered due to router error: {str(exc)}"
            },
            "validation_errors": [f"Gateway Fallback Triggered: {str(exc)}"]
        }
