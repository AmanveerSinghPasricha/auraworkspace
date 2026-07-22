"""
Aura Gateway Core - Production Pure-LLM Router Node

Classifies incoming user prompts using LiteLLM + Instructor structured output across 
three target domains (rag_node, general_agent_node, extraction_node). Features slot memory,
LLM-native contextual resolution, token-budgeted pruning, and FinOps ledger tracking.
"""

import os
import logging
from typing import Dict, Any, List, Literal, Optional
from pydantic import BaseModel, Field
import instructor
from litellm import acompletion
from langchain_core.messages import BaseMessage
from app.state import GraphState

logger = logging.getLogger(__name__)

# Wrap LiteLLM with Instructor for strict schema enforcement and retries
instructor_client = instructor.from_litellm(acompletion)


# ─────────────────────────────────────────────────────────────
# 1. ROUTER STATE — Slot memory tracking across turns
# ─────────────────────────────────────────────────────────────
class RouterState(BaseModel):
    """
    Structured slot memory tracking intent state across turns.
    Saves state metadata for downstream nodes.
    """
    last_intent: Optional[Literal["extraction", "rag", "general"]] = None
    last_document_ref: Optional[str] = None
    last_target_ref: Optional[str] = None
    last_entity_ref: Optional[str] = None
    turn_count: int = 0

    def reset_slots(self):
        """Clears stale slot memory when intent context shifts."""
        self.last_document_ref = None
        self.last_target_ref = None
        self.last_entity_ref = None


# ─────────────────────────────────────────────────────────────
# 2. LLM REWRITER — Pure LLM contextualization
# ─────────────────────────────────────────────────────────────
CONTEXTUALIZE_PROMPT = """Given recent conversation turns and a follow-up user message, rewrite the
message as a standalone query containing all necessary context (such as document references, target fields, or entities mentioned earlier).
If the message is already standalone, return it unchanged. Output ONLY the rewritten query."""


async def resolve_query(
    query: str,
    recent_messages: List[Dict[str, str]],
    model: str = "gpt-4o-mini",
) -> str:
    """Delegates context resolution 100% to the LLM without brittle Python keyword matching."""
    if not recent_messages:
        return query

    llm_messages = (
        [{"role": "system", "content": CONTEXTUALIZE_PROMPT}]
        + recent_messages[-4:]
        + [{"role": "user", "content": query}]
    )
    try:
        response = await acompletion(
            model=model,
            messages=llm_messages,
            temperature=0.0,
            max_tokens=120,
            timeout=5,
            fallbacks=[os.getenv("LLM_ROUTER_FALLBACK_MODEL", "claude-3-5-haiku-20241022")],
        )
        rewritten = response.choices[0].message.content.strip()
        return rewritten if rewritten else query
    except Exception as e:
        logger.warning(f"[CONTEXTUALIZE] Contextualization failed, using raw query: {e}")
        return query


# ─────────────────────────────────────────────────────────────
# 3. ROUTER SCHEMA & PROMPT (Chain-of-Thought ordering)
# ─────────────────────────────────────────────────────────────
class RouteDecisionSchema(BaseModel):
    reasoning: str = Field(
        description=(
            "Step-by-step evaluation of user intent. Analyze: "
            "1. Is the user asking questions, seeking explanations, or requesting summaries grounded in an uploaded document? -> 'rag_node' "
            "2. Is the user explicitly asking for raw OCR, coordinate parsing, or grid table extractions? -> 'extraction_node' "
            "3. Is this general chat, coding, or web search without document grounding? -> 'general_agent_node'"
        )
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Certainty score between 0.0 and 1.0 based on intent clarity."
    )
    next_node: Literal["rag_node", "extraction_node", "general_agent_node"] = Field(
        description="Final target graph node based on the reasoned evaluation."
    )


SYSTEM_ROUTER_PROMPT = """You are the Central Gateway Routing Intelligence for Aura Gateway Core.
Classify user intent with maximum precision and zero hallucination.

### TARGET NODES & RESPONSIBILITIES:
1. `rag_node` (Vectorless Document RAG Engine):
   - USE WHEN: The user query is asking questions, seeking explanations, requesting summaries, or retrieving details grounded in an uploaded document or file reference (e.g., "explain this document", "what is the revenue in section 3?", "summarize page 12").

2. `general_agent_node` (General Agent & Web Search):
   - USE WHEN: The query requires general Q&A, general web search, real-time web grounding, coding, or standard conversational interaction WITHOUT requiring an uploaded document.

3. `extraction_node` (OCR & Coordinate Extraction):
   - USE WHEN: The user explicitly requests raw OCR coordinate parsing, grid cell matrix extraction, or bounding box extraction from structured form files.

### OPERATIONAL CONSTRAINTS:
- Evaluate the latest user query in light of the provided context.
- Be conservative: if intent is ambiguous, assign confidence < 0.60 so the system defaults safely.
"""


# ─────────────────────────────────────────────────────────────
# 4. PRIMARY SUPERVISOR ROUTER NODE
# ─────────────────────────────────────────────────────────────
async def supervisor_router_node(state: GraphState) -> Dict[str, Any]:
    print("🧠 [LLM GATEWAY ROUTER] Classifying query intent via Pure LLM Engine...")

    messages = state.messages
    if not messages:
        logger.warning("[LLM ROUTER] No messages found in state.")
        return {
            "active_loop_count": state.active_loop_count + 1,
            "validation_errors": ["No messages found in execution state for routing."]
        }

    # Extract text content safely even if message contains multimodal data
    raw_content = messages[-1].content
    current_query = raw_content if isinstance(raw_content, str) else str(raw_content)

    recent_as_dicts = [
        {"role": "user" if m.type == "human" else "assistant", "content": str(m.content)}
        for m in messages[:-1][-4:]
    ]

    # Step 1: Contextualize Query via LLM
    resolved_query = await resolve_query(
        query=current_query,
        recent_messages=recent_as_dicts,
    )

    formatted_messages = [
        {"role": "system", "content": SYSTEM_ROUTER_PROMPT},
        {"role": "user", "content": f"[Current query]: {resolved_query}"},
    ]

    router_model = os.getenv("LLM_ROUTER_MODEL", "gpt-4o-mini")
    gateway_api_base = os.getenv("LLM_GATEWAY_API_BASE", None)

    try:
        # Step 2: Classify Intent using Instructor Structured Output
        decision, raw_response = await instructor_client.chat.completions.create_with_completion(
            model=router_model,
            messages=formatted_messages,
            response_model=RouteDecisionSchema,
            temperature=0.0,
            api_base=gateway_api_base,
            max_retries=2,
        )

        # Step 3: Immutable FinOps Usage Logging
        new_finops_ledger = state.finops_ledger.model_copy(deep=True)
        if hasattr(raw_response, "usage") and raw_response.usage:
            usage = raw_response.usage
            new_finops_ledger.log_transaction_usage(
                model_response_metadata={
                    "prompt_tokens": getattr(usage, "prompt_tokens", 0),
                    "completion_tokens": getattr(usage, "completion_tokens", 0),
                    "cache_read_tokens": getattr(usage, "prompt_tokens_details", {}).get("cached_tokens", 0)
                    if hasattr(usage, "prompt_tokens_details") else 0,
                },
                model_pricing_rates={"in": 0.00000015, "cached": 0.000000075, "out": 0.0000006},
            )

        target_route = decision.next_node
        if decision.confidence < 0.60:
            print(f"⚠️ [LLM ROUTER] Low confidence ({decision.confidence:.2f}). Defaulting to general_agent_node.")
            target_route = "general_agent_node"

        # Step 4: Safe Router State Deep Copy & Reset
        new_router_state = state.router_state.model_copy(deep=True)
        new_router_state.turn_count += 1
        
        if target_route == "general_agent_node" and new_router_state.last_intent in ["extraction", "rag"]:
            new_router_state.reset_slots()
            
        new_router_state.last_intent = "rag" if target_route == "rag_node" else ("extraction" if target_route == "extraction_node" else "general")

        print(
            f"🔀 [LLM GATEWAY ROUTER] Selected Route: '{target_route}' "
            f"(Confidence: {decision.confidence:.2f}) | Resolved Query: '{resolved_query}'"
        )

        return {
            "active_loop_count": state.active_loop_count + 1,
            "validation_errors": [],
            "router_state": new_router_state,
            "finops_ledger": new_finops_ledger,
            "staged_action_payload": {
                "selected_route": target_route,
                "confidence": decision.confidence,
                "reasoning": decision.reasoning,
                "resolved_query": resolved_query,
            }
        }

    except Exception as router_error:
        print(f"❌ [LLM ROUTER ERROR] Intent classification failed: {str(router_error)}")
        return {
            "active_loop_count": state.active_loop_count + 1,
            "validation_errors": [f"Gateway Fallback Triggered: {str(router_error)}"],
            "staged_action_payload": None,
        }


# ─────────────────────────────────────────────────────────────
# 5. CONDITIONAL EDGE FUNCTION
# ─────────────────────────────────────────────────────────────
def route_decision(state: GraphState) -> Literal["rag_node", "extraction_node", "general_agent_node", "__end__"]:
    if state.active_loop_count > 10:
        print("⚠️ [LLM ROUTER] Max recursion limit reached (10). Terminating thread execution.")
        return "__end__"

    if state.staged_action_payload and "selected_route" in state.staged_action_payload:
        route = state.staged_action_payload["selected_route"]
        if route in ["rag_node", "extraction_node", "general_agent_node"]:
            return route

    return "general_agent_node"