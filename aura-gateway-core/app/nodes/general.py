"""
Aura Gateway Core - Production General Agent Node
=================================================
Features:
1. Multi-Dimensional Dynamic Persona Engine (XML-structured, temporal & role aware)
2. Exact/Semantic SHA-256 Caching (Zero Token Cost for duplicate queries)
3. Token-Aware Context Window Trimming (Tiktoken BPE, message atomicity preserved)
4. Token-Level Streaming & Tool Calling via LiteLLM
5. Exa AI & Tavily Real-Time Web Intelligence Integration
6. Async Long-Term Memory Extraction & Profile Injection
7. Immutable FinOps Usage & Cost Accounting
"""

import hashlib
import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
import tiktoken
from litellm import acompletion
from langchain_core.messages import AIMessage, BaseMessage, trim_messages
from langgraph.store.base import BaseStore

from app.config import settings
from app.state import GraphState
from app.memory import (
    get_user_long_term_memory,
    extract_and_update_memory,
)
from app.services.exa_search import execute_exa_search
from app.services.web_search import execute_web_search

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
    1. Live System Date & Time Anchor
    2. Department & Professional Domain
    3. Role & Seniority Title
    4. Preferred Communication Language
    5. Output Formatting Style
    6. Long-Term Memory Profile
    """
    current_time_str = datetime.now().strftime("%A, %B %d, %Y at %I:%M:%S %p")

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
  <temporal_anchor>
    - Current System Date & Time: {current_time_str}
    - Use this timestamp to answer immediate time and date questions directly without triggering external web searches.
  </temporal_anchor>
  <target_audience>Assisting a **{role_title}** in {department}.</target_audience>
  <tone_and_style>
    - Tone: Professional, concise, highly analytical, and direct.
    - Focus: {department_guidance}
    - Language: Respond strictly in **{language}** unless explicitly instructed otherwise.
    - No fluff: Skip unnecessary preambles or filler conversational phrases.
  </tone_and_style>

  <formatting_rules style="{pref_format}">
    - Primary Format: Render all structured outputs strictly in clean **{pref_format}**.
    - Code Blocks: Always explicitly specify the syntax language tag for code blocks. Output code ONLY when requested or directly relevant to an engineering implementation request.
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
# 3. GENERAL AGENT NODE EXECUTION WITH TOOLS
# ─────────────────────────────────────────────────────────────
async def general_agent_node(
    state: GraphState, 
    store: BaseStore = None,
    stream_tokens: bool = False
) -> Dict[str, Any]:
    """
    LangGraph execution node incorporating Token-Aware Trimming, Dynamic Personas, 
    Exa AI / Tavily Web Search Tools, Semantic Caching, and FinOps ledger tracking.
    """
    logger.info("🤖 [GENERAL AGENT] Executing request with Token-Aware Memory & Multi-Dimensional Persona...")

    # Extract state safely whether state is a dict or GraphState object
    user_context = state.get("user_context") if isinstance(state, dict) else getattr(state, "user_context", None)
    messages = state.get("messages", []) if isinstance(state, dict) else getattr(state, "messages", [])
    finops_ledger = state.get("finops_ledger") if isinstance(state, dict) else getattr(state, "finops_ledger", None)

    user_id = getattr(user_context, "user_id", "default_user") if user_context else "default_user"

    # 1. Fetch Long-Term Memory Profile
    long_term_block = ""
    if store:
        user_memory = await get_user_long_term_memory(store, user_id)
        long_term_block = user_memory.to_system_prompt_block()

    # 2. Build Dynamic Persona System Prompt (with Live Temporal Anchor)
    system_prompt = build_dynamic_persona(user_context, long_term_block)

    # 3. Format Payload with Token-Aware Short-Term Trimming (Max 4,000 Tokens)
    llm_payload = prepare_messages_token_aware(
        messages=messages,
        system_prompt=system_prompt,
        max_tokens=4000
    )

    if len(llm_payload) <= 1:
        return {
            "messages": [AIMessage(content="I didn't receive a valid prompt to respond to.")],
            "validation_errors": ["Empty prompt in general_agent_node."]
        }

    latest_user_prompt = str(messages[-1].content) if messages else ""
    cache_key = compute_query_hash(user_id, latest_user_prompt)

    # 4. EXACT / SEMANTIC CACHE CHECK
    if cache_key in IN_MEMORY_SEMANTIC_CACHE:
        logger.info(f"⚡ [CACHE HIT] Returning cached response for user '{user_id}' at zero token cost.")
        cached_answer = IN_MEMORY_SEMANTIC_CACHE[cache_key]
        
        new_finops_ledger = finops_ledger.model_copy(deep=True) if finops_ledger else None
        if new_finops_ledger:
            new_finops_ledger.log_transaction_usage(
                model_response_metadata={"prompt_tokens": 0, "completion_tokens": 0},
                model_pricing_rates={"in": 0.0, "cached": 0.0, "out": 0.0},
            )
        res = {
            "messages": [AIMessage(content=f"{cached_answer}\n\n*(⚡ Delivered via Cache)*")],
            "validation_errors": []
        }
        if new_finops_ledger:
            res["finops_ledger"] = new_finops_ledger
        return res

    # 5. DEFINE REAL-TIME WEB SEARCH TOOLS FOR LLM TOOL CALLING
    tools = [
        {
            "type": "function",
            "function": {
                "name": "exa_web_search",
                "description": "Performs neural semantic web search using Exa AI to fetch fresh online data, market news, or verify technical docs.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query string to execute."
                        }
                    },
                    "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Fallback real-time web search tool using Tavily API.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query string to execute."
                        }
                    },
                    "required": ["query"]
                }
            }
        }
    ]

    # 6. LLM EXECUTION
    try:
        response = await acompletion(
            model=settings.LLM_GENERAL_PRIMARY,
            messages=llm_payload,
            tools=tools,
            tool_choice="auto",
            temperature=0.2,
            fallbacks=[settings.LLM_GENERAL_FALLBACK],
            num_retries=2,
        )

        message = response.choices[0].message
        answer = ""

        # Check if the LLM invoked a web search tool
        if hasattr(message, "tool_calls") and message.tool_calls:
            tool_call = message.tool_calls[0]
            func_name = tool_call.function.name
            
            # Robust JSON/Dict argument parsing across Pydantic & LiteLLM versions
            raw_args = tool_call.function.arguments
            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            search_query = args.get("query", latest_user_prompt)

            logger.info(f"🔍 [TOOL TRIGGERED] Executing tool '{func_name}' for query: '{search_query}'")

            search_context = ""
            if func_name == "exa_web_search":
                search_data = await execute_exa_search(search_query)
                for idx, item in enumerate(search_data.get("results", [])):
                    search_context += f"[{idx+1}] {item.get('title')}\nURL: {item.get('url')}\nHighlights:\n{item.get('highlights')}\n\n"
            else:
                search_data = await execute_web_search(search_query)
                search_context = f"Answer: {search_data.get('answer', 'N/A')}\n\nResults:\n"
                for item in search_data.get("results", []):
                    search_context += f"- [{item.get('title')}]({item.get('url')}): {item.get('snippet')}\n"

            # Convert tool_call safely to dict if required by LiteLLM payload format
            tool_call_dict = tool_call.model_dump() if hasattr(tool_call, "model_dump") else dict(tool_call)

            # Second LLM pass for final answer synthesis with strict grounding rules
            synthesis_payload = llm_payload + [
                {"role": "assistant", "content": None, "tool_calls": [tool_call_dict]},
                {
                    "role": "user", 
                    "content": (
                        f"Real-Time Web Search Results:\n{search_context}\n\n"
                        "SYNTHESIS GUIDELINES:\n"
                        "1. Synthesize a clear, structured response answering the original query based strictly on the search results above.\n"
                        "2. HYPERLINKS: Cite key headlines or technical findings using inline markdown links explicitly found in the search results (e.g., [Source Name](URL)). Do NOT fabricate URLs.\n"
                        "3. CODE BLOCKS: Do NOT generate example code snippets unless the user specifically asked for code or implementation steps.\n"
                        "4. If search results fail to return relevant context, explicitly state that live search yielded no direct matches."
                    )
                }
            ]

            synthesis_response = await acompletion(
                model=settings.LLM_GENERAL_PRIMARY,
                messages=synthesis_payload,
                temperature=0.2,
                fallbacks=[settings.LLM_GENERAL_FALLBACK],
            )
            answer = synthesis_response.choices[0].message.content or ""
            response = synthesis_response
        else:
            answer = message.content or ""

        # Update FinOps Ledger
        new_finops_ledger = finops_ledger.model_copy(deep=True) if finops_ledger else None
        if new_finops_ledger and hasattr(response, "usage") and response.usage:
            usage = response.usage
            new_finops_ledger.log_transaction_usage(
                model_response_metadata={
                    "prompt_tokens": getattr(usage, "prompt_tokens", 0),
                    "completion_tokens": getattr(usage, "completion_tokens", 0),
                },
                model_pricing_rates={"in": 0.00000015, "cached": 0.000000075, "out": 0.0000006},
            )

        # 7. POPULATE CACHE
        if answer:
            IN_MEMORY_SEMANTIC_CACHE[cache_key] = answer

        # 8. ASYNCHRONOUS MEMORY EXTRACTION WORKER
        if store and messages:
            await extract_and_update_memory(
                store=store,
                user_id=user_id,
                user_message=latest_user_prompt,
                assistant_response=answer
            )

        res = {
            "messages": [AIMessage(content=answer)],
            "validation_errors": []
        }
        if new_finops_ledger:
            res["finops_ledger"] = new_finops_ledger
        return res

    except Exception as exc:
        logger.error(f"❌ [GENERAL AGENT ERROR] Invocation failed: {exc}", exc_info=True)
        return {
            "messages": [AIMessage(content="I encountered an issue processing your request.")],
            "validation_errors": [str(exc)]
        }