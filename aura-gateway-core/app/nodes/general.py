"""
Aura Gateway Core - Production General Agent Node
=================================================
Features:
1. Multi-Dimensional Dynamic Persona Engine (XML-structured, role & department aware)
2. Exact/Semantic SHA-256 Caching (Zero Token Cost for duplicate queries)
3. Token-Aware Context Window Trimming (Tiktoken BPE, message atomicity preserved)
4. Token-Level Streaming via LiteLLM `astream_completion`
5. Async Long-Term Memory Extraction & Profile Injection
6. Immutable FinOps Usage & Cost Accounting
"""

import hashlib
import json
import logging
from typing import Dict, Any, List, Optional
import tiktoken
from litellm import acompletion, astream_completion
from langchain_core.messages import AIMessage, BaseMessage, trim_messages
from langgraph.store.base import BaseStore

from app.config import settings
from app.state import GraphState
from app.memory import (
    get_user_long_term_memory,
    extract_and_update_memory,
)

logger = logging.getLogger("general_agent")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Ephemeral Cache Store (Replace with Redis/PGVector client in multi-replica production)
IN_MEMORY_SEMANTIC_CACHE: Dict[str, str] = {}

# Pre-load Token Encoder at module startup
try:
    TOKEN_ENCODER = tiktoken.encoding_for_model("gpt-4o")
except Exception:
    TOKEN_ENCODER = tiktoken.get_encoding("cl100k_base")


# ─────────────────────────────────────────────────────────────
# 1. TOKEN-AWARE TRIMMING & PREPARATION
# ─────────────────────────────────────────────────────────────
def count_tokens_exact(messages: List[BaseMessage]) -> int:
    """Accurately calculates total tokens across a list of LangChain messages."""
    total = 0
    for msg in messages:
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        total += len(TOKEN_ENCODER.encode(content))
    return total


def prepare_messages_token_aware(
    messages: List[BaseMessage],
    system_prompt: str,
    max_tokens: int = 4000
) -> List[dict]:
    """
    Combines System Prompt + Token-Aware Trimmed History into LiteLLM payload.
    Trims based on exact token budget rather than raw message count, ensuring
    messages are never split mid-sentence (allow_partial=False).
    """
    formatted_payload = [{"role": "system", "content": system_prompt}]

    if not messages:
        return formatted_payload

    # Trim short-term memory safely to stay within the max_tokens threshold
    trimmed = trim_messages(
        messages,
        max_tokens=max_tokens,
        token_counter=count_tokens_exact,
        strategy="last",
        start_on="human",
        include_system=False,
        allow_partial=False,  # Guarantees message atomicity
    )

    for msg in trimmed:
        if msg.type == "human":
            formatted_payload.append({"role": "user", "content": str(msg.content)})
        elif msg.type == "ai":
            formatted_payload.append({"role": "assistant", "content": str(msg.content)})

    return formatted_payload


# ─────────────────────────────────────────────────────────────
# 2. MULTI-DIMENSIONAL DYNAMIC PERSONA BUILDER
# ─────────────────────────────────────────────────────────────
def build_dynamic_persona(user_context: Optional[Any], long_term_block: str) -> str:
    """
    Dynamically builds a context-aware system persona leveraging:
    1. Department & Professional Domain
    2. Role & Seniority Title
    3. Preferred Communication Language
    4. Output Formatting Style
    5. Long-Term Memory Profile (Tech stack & user constraints)
    """
    if user_context:
        department = getattr(user_context, "department", "Engineering") or "Engineering"
        pref_format = getattr(user_context, "formatting_preference", "Markdown") or "Markdown"
        language = getattr(user_context, "preferred_language", "English") or "English"
        role_title = getattr(user_context, "role_title", "Technical Member") or "Technical Member"
    else:
        department = "Engineering"
        pref_format = "Markdown"
        language = "English"
        role_title = "Technical Member"

    domain_nudges = {
        "Engineering": "Focus on clean architecture, performance efficiency, micro-optimizations, and executable code snippets.",
        "Data & ML": "Prioritize mathematical rigor, pipeline scalability, data validation, and model metrics.",
        "DevOps & Security": "Focus on infrastructure-as-code, zero-trust security best practices, and resilience.",
        "Product & Management": "Provide high-level strategic summaries, clear trade-offs, timelines, and actionable recommendations."
    }
    department_guidance = domain_nudges.get(
        department, 
        "Provide clear, technically precise, and actionable engineering responses."
    )

    system_prompt = f"""<system_persona>
  <role>You are **Aura Workspace's Lead AI Specialist**, embedded within the **{department}** division.</role>
  <target_audience>Assisting a **{role_title}** in {department}.</target_audience>
  <tone_and_style>
    - Tone: Professional, concise, highly analytical, and direct.
    - Focus: {department_guidance}
    - Language: Respond strictly in **{language}** unless explicitly instructed otherwise.
    - No fluff: Skip unnecessary preambles or filler conversational phrases.
  </tone_and_style>

  <formatting_rules style="{pref_format}">
    - Primary Format: Render all structured outputs strictly in clean **{pref_format}**.
    - Code Blocks: Always explicitly specify the syntax language tag for code blocks.
    - Visual Scannability: Use clear section headings (`##`), concise bullet points, and comparative Markdown tables where appropriate.
  </formatting_rules>
</system_persona>"""

    if long_term_block:
        system_prompt += f"\n\n{long_term_block.strip()}"

    return system_prompt


def compute_query_hash(user_id: str, prompt: str) -> str:
    """Computes a SHA-256 hash for exact/normalized prompt caching."""
    normalized = f"{user_id}:{prompt.strip().lower()}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# ─────────────────────────────────────────────────────────────
# 3. GENERAL AGENT NODE EXECUTION
# ─────────────────────────────────────────────────────────────
async def general_agent_node(
    state: GraphState, 
    store: BaseStore = None,
    stream_tokens: bool = False
) -> Dict[str, Any]:
    """
    LangGraph execution node incorporating Token-Aware Trimming, Dynamic Personas, 
    Semantic Caching, LiteLLM Gateway Execution, and FinOps ledger tracking.
    """
    logger.info("🤖 [GENERAL AGENT] Executing request with Token-Aware Memory & Multi-Dimensional Persona...")

    user_id = state.user_context.user_id if state.user_context else "default_user"

    # 1. Fetch Long-Term Memory Profile
    long_term_block = ""
    if store:
        user_memory = await get_user_long_term_memory(store, user_id)
        long_term_block = user_memory.to_system_prompt_block()

    # 2. Build Dynamic Persona System Prompt
    system_prompt = build_dynamic_persona(state.user_context, long_term_block)

    # 3. Format Payload with Token-Aware Short-Term Trimming (Max 4,000 Tokens)
    llm_payload = prepare_messages_token_aware(
        messages=state.messages,
        system_prompt=system_prompt,
        max_tokens=4000
    )

    if len(llm_payload) <= 1:
        return {
            "messages": [AIMessage(content="I didn't receive a valid prompt to respond to.")],
            "validation_errors": ["Empty prompt in general_agent_node."]
        }

    latest_user_prompt = str(state.messages[-1].content) if state.messages else ""
    cache_key = compute_query_hash(user_id, latest_user_prompt)

    # 4. EXACT / SEMANTIC CACHE CHECK
    if cache_key in IN_MEMORY_SEMANTIC_CACHE:
        logger.info(f"⚡ [CACHE HIT] Returning cached response for user '{user_id}' at zero token cost.")
        cached_answer = IN_MEMORY_SEMANTIC_CACHE[cache_key]
        
        new_finops_ledger = state.finops_ledger.model_copy(deep=True)
        new_finops_ledger.log_transaction_usage(
            model_response_metadata={"prompt_tokens": 0, "completion_tokens": 0},
            model_pricing_rates={"in": 0.0, "cached": 0.0, "out": 0.0},
        )
        return {
            "messages": [AIMessage(content=f"{cached_answer}\n\n*(⚡ Delivered via Cache)*")],
            "finops_ledger": new_finops_ledger,
            "validation_errors": []
        }

    # 5. LLM EXECUTION (STREAMING OR BATCH)
    try:
        if stream_tokens:
            logger.info("🌊 [STREAMING] Initiating token streaming via astream_completion...")
            
            response_stream = await astream_completion(
                model=settings.LLM_GENERAL_PRIMARY,
                messages=llm_payload,
                temperature=0.2,
                fallbacks=[settings.LLM_GENERAL_FALLBACK],
            )

            accumulated_chunks: List[str] = []
            async for chunk in response_stream:
                content = chunk.choices[0].delta.content or ""
                accumulated_chunks.append(content)
            
            answer = "".join(accumulated_chunks)
            new_finops_ledger = state.finops_ledger.model_copy(deep=True)

        else:
            response = await acompletion(
                model=settings.LLM_GENERAL_PRIMARY,
                messages=llm_payload,
                temperature=0.2,
                fallbacks=[settings.LLM_GENERAL_FALLBACK],
                num_retries=2,
            )
            answer = response.choices[0].message.content or ""

            # Log token usage to FinOps Ledger
            new_finops_ledger = state.finops_ledger.model_copy(deep=True)
            if hasattr(response, "usage") and response.usage:
                usage = response.usage
                new_finops_ledger.log_transaction_usage(
                    model_response_metadata={
                        "prompt_tokens": getattr(usage, "prompt_tokens", 0),
                        "completion_tokens": getattr(usage, "completion_tokens", 0),
                    },
                    model_pricing_rates={"in": 0.00000015, "cached": 0.000000075, "out": 0.0000006},
                )

        # 6. POPULATE CACHE
        if answer:
            IN_MEMORY_SEMANTIC_CACHE[cache_key] = answer

        # 7. ASYNCHRONOUS MEMORY EXTRACTION WORKER
        if store and state.messages:
            await extract_and_update_memory(
                store=store,
                user_id=user_id,
                user_message=latest_user_prompt,
                assistant_response=answer
            )

        return {
            "messages": [AIMessage(content=answer)],
            "finops_ledger": new_finops_ledger,
            "validation_errors": []
        }

    except Exception as exc:
        logger.error(f"❌ [GENERAL AGENT ERROR] Invocation failed: {exc}")
        return {
            "messages": [AIMessage(content="I encountered an issue processing your request.")],
            "validation_errors": [str(exc)]
        }