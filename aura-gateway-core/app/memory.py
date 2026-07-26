"""
Aura Gateway Core - Production Memory Manager
=============================================
Handles Long-Term Memory (UserProfileMemory + AsyncPostgresStore + Semantic Deduplication)
and Short-Term Memory (Sliding Window Trimming + Recursive Summarization).
"""

import json
import logging
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field
from langgraph.store.base import BaseStore
from langchain_core.messages import (
    BaseMessage,
    SystemMessage,
    HumanMessage,
    AIMessage,
    ToolMessage,
    trim_messages,
)
from litellm import acompletion

from app.config import settings

logger = logging.getLogger(__name__)

SLIDING_WINDOW_MSG_COUNT = 6


# =====================================================================
# 1. LONG-TERM MEMORY SCHEMAS & STORE OPERATIONS
# =====================================================================
class UserProfileMemory(BaseModel):
    """Structured long-term memory schema stored in PostgreSQL per user."""
    user_id: str
    preferred_language: str = "English"
    technical_stack: List[str] = Field(default_factory=list)
    domain_facts: List[str] = Field(default_factory=list)
    explicit_instructions: List[str] = Field(default_factory=list)

    class Config:
        extra = "ignore"

    def to_system_prompt_block(self) -> str:
        """Formats long-term memory into an XML block for LLM compliance."""
        if not (self.domain_facts or self.explicit_instructions or self.technical_stack):
            return ""

        facts_str = "\n".join([f"  * {f}" for f in self.domain_facts]) if self.domain_facts else "  * None recorded"
        instructions_str = "\n".join([f"  * {i}" for i in self.explicit_instructions]) if self.explicit_instructions else "  * None recorded"
        stack_str = ", ".join(self.technical_stack) if self.technical_stack else "Unspecified"

        return f"""
<long_term_user_profile>
  <preferred_language>{self.preferred_language}</preferred_language>
  <technical_stack>{stack_str}</technical_stack>
  <explicit_user_constraints>
{instructions_str}
  </explicit_user_constraints>
  <remembered_facts>
{facts_str}
  </remembered_facts>
</long_term_user_profile>
"""


async def get_user_long_term_memory(store: BaseStore, user_id: str) -> UserProfileMemory:
    """Retrieves long-term memory from AsyncPostgresStore or returns a default schema."""
    namespace: Tuple[str, str] = ("users", user_id)
    key = "profile"

    try:
        item = await store.aget(namespace=namespace, key=key)
        if item and item.value:
            return UserProfileMemory(**item.value)
    except Exception as err:
        logger.warning(f"?? [LONG-TERM MEMORY] Failed to fetch profile for user {user_id}: {err}")

    return UserProfileMemory(user_id=user_id)


async def save_user_profile(store: BaseStore, user_id: str, profile: UserProfileMemory) -> None:
    """Persists an updated UserProfileMemory model back to AsyncPostgresStore."""
    namespace: Tuple[str, str] = ("users", user_id)
    key = "profile"

    await store.aput(
        namespace=namespace,
        key=key,
        value=profile.model_dump()
    )
    logger.info(f"?? [LONG-TERM MEMORY] Saved profile for user '{user_id}'.")


# =====================================================================
# 2. FACT RECONCILIATION & DEDUPLICATION
# =====================================================================
RECONCILE_FACTS_PROMPT = """You are a Memory Management System.
Your job is to merge new facts into an existing list of user facts, preventing duplicates and resolving contradictions.

Rules:
1. Merge semantically similar or overlapping facts into a single concise fact.
2. If a new fact directly contradicts an old fact, update it with the newest information.
3. Keep the resulting list clear, high-density, and non-redundant.
4. Output JSON strictly matching the format: {{"consolidated_facts": ["fact 1", "fact 2"]}}

Existing Facts:
{existing_facts}

New Facts to Process:
{new_facts}"""


async def reconcile_and_save_facts(
    store: BaseStore, 
    user_id: str, 
    candidate_facts: List[str]
) -> None:
    """Reconciles new candidate facts against existing stored memory using LLM deduplication."""
    if not candidate_facts:
        return

    profile = await get_user_long_term_memory(store, user_id)
    existing_facts = profile.domain_facts

    if not existing_facts:
        profile.domain_facts = list(set(candidate_facts))
        await save_user_profile(store, user_id, profile)
        return

    prompt = RECONCILE_FACTS_PROMPT.format(
        existing_facts=json.dumps(existing_facts),
        new_facts=json.dumps(candidate_facts)
    )

    try:
        response = await acompletion(
            model=settings.LLM_ROUTER_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            response_format={"type": "json_object"},
            fallbacks=[settings.LLM_ROUTER_FALLBACK],
            timeout=8,
        )

        result = json.loads(response.choices[0].message.content or "{}")
        consolidated = result.get("consolidated_facts", existing_facts)

        profile.domain_facts = consolidated
        await save_user_profile(store, user_id, profile)
        logger.info(f"?? [MEMORY DEDUPLICATION] Reconciled facts for user '{user_id}'. Count: {len(consolidated)}")

    except Exception as exc:
        logger.error(f"? [DEDUPLICATION ERROR] Failed to reconcile facts: {exc}")


MEMORY_EXTRACTION_PROMPT = """Analyze the following conversation turn between a User and Assistant.
Determine if the User explicitly shared any NEW long-term facts, personal preferences, technical stack details, or explicit constraints that should be remembered across future chat sessions.

Rules:
1. ONLY extract information that has long-term relevance (e.g., tech stack preferences, persistent guidelines, domain roles).
2. DO NOT extract transient queries or temporary context.
3. Return valid JSON matching the schema below. If no new information is found, return empty arrays.

Output JSON Format:
{
  "new_facts": ["fact 1", "fact 2"],
  "new_instructions": ["constraint 1"],
  "technical_stack_items": ["python", "fastapi"]
}"""


async def extract_and_update_memory(
    store: BaseStore, 
    user_id: str, 
    user_message: str, 
    assistant_response: str
) -> None:
    """Extracts new facts from a conversation turn and applies semantic deduplication."""
    profile = await get_user_long_term_memory(store, user_id)
    prompt = f"{MEMORY_EXTRACTION_PROMPT}\n\nUser: {user_message}\nAssistant: {assistant_response}"

    try:
        response = await acompletion(
            model=settings.LLM_ROUTER_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            response_format={"type": "json_object"},
            fallbacks=[settings.LLM_ROUTER_FALLBACK],
            timeout=8,
        )

        extracted = json.loads(response.choices[0].message.content or "{}")

        new_facts = extracted.get("new_facts", [])
        new_instructions = extracted.get("new_instructions", [])
        tech_items = extracted.get("technical_stack_items", [])

        updated_profile = False
        for instr in new_instructions:
            if instr and instr not in profile.explicit_instructions:
                profile.explicit_instructions.append(instr)
                updated_profile = True

        for item in tech_items:
            if item and item not in profile.technical_stack:
                profile.technical_stack.append(item)
                updated_profile = True

        if updated_profile:
            await save_user_profile(store, user_id, profile)

        if new_facts:
            await reconcile_and_save_facts(store, user_id, new_facts)

    except Exception as exc:
        logger.error(f"? [MEMORY EXTRACTION ERROR] Failed to extract facts: {exc}")


# =====================================================================
# 3. SHORT-TERM MEMORY (SLIDING WINDOW & SUMMARIZATION)
# =====================================================================
def trim_sliding_window(
    messages: List[BaseMessage], 
    max_messages: int = SLIDING_WINDOW_MSG_COUNT
) -> List[BaseMessage]:
    """Applies sliding window strategy using LangChain's trim_messages."""
    if not messages:
        return []

    return trim_messages(
        messages,
        max_tokens=max_messages,
        token_counter=len,
        strategy="last",
        start_on="human",
        include_system=True,
        allow_partial=False,
    )


def _format_message_for_transcript(msg: BaseMessage) -> str:
    """Formats any BaseMessage variant into plain text for summary prompts."""
    content = msg.content if isinstance(msg.content, str) else str(msg.content)

    if isinstance(msg, HumanMessage):
        return f"User: {content}"
    elif isinstance(msg, AIMessage):
        return f"Assistant: {content}"
    elif isinstance(msg, SystemMessage):
        return f"System Instruction: {content}"
    elif isinstance(msg, ToolMessage):
        tool_name = getattr(msg, "name", "tool")
        return f"Tool Result ({tool_name}): {content}"

    return f"Speaker: {content}"


async def summarize_older_messages(
    messages: List[BaseMessage], 
    existing_summary: str = ""
) -> Tuple[str, List[BaseMessage]]:
    """Compresses older conversation turns into a running summary block."""
    chat_messages = [m for m in messages if not isinstance(m, SystemMessage)]

    if len(chat_messages) <= SLIDING_WINDOW_MSG_COUNT:
        return existing_summary, messages

    older_turns = chat_messages[:-SLIDING_WINDOW_MSG_COUNT]
    recent_turns = chat_messages[-SLIDING_WINDOW_MSG_COUNT:]

    transcript = "\n".join([_format_message_for_transcript(m) for m in older_turns])

    prompt = f"""Synthesize the following conversation history into a concise, high-density running summary block.
Preserve key decisions, active intent, technical metrics, and constraints.

Existing Summary:
{existing_summary or 'None'}

Older Conversation Turns to Compress:
{transcript}

Updated Running Summary:"""

    try:
        response = await acompletion(
            model=settings.LLM_ROUTER_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            fallbacks=[settings.LLM_ROUTER_FALLBACK],
            timeout=10,
        )

        updated_summary = response.choices[0].message.content.strip()
        logger.info("?? [SHORT-TERM MEMORY] Successfully compressed older turns into running summary.")

        system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
        return updated_summary, system_msgs + recent_turns

    except Exception as exc:
        logger.error(f"? [SHORT-TERM MEMORY ERROR] Summarization failed: {exc}")
        trimmed_fallback = trim_sliding_window(messages, max_messages=SLIDING_WINDOW_MSG_COUNT)
        return existing_summary, trimmed_fallback


def prepare_messages_for_llm(
    messages: List[BaseMessage],
    system_prompt: str,
    running_summary: str = "",
    max_messages: int = SLIDING_WINDOW_MSG_COUNT
) -> List[dict]:
    """Combines System Prompt + Summary + Trimmed Window into LiteLLM format."""
    full_system_content = system_prompt
    if running_summary:
        full_system_content += f"\n\n### RUNNING CONVERSATION SUMMARY (Older Turns):\n{running_summary}"

    formatted_payload = [{"role": "system", "content": full_system_content}]
    trimmed = trim_sliding_window(messages, max_messages=max_messages)

    for msg in trimmed:
        if isinstance(msg, HumanMessage):
            formatted_payload.append({"role": "user", "content": str(msg.content)})
        elif isinstance(msg, AIMessage):
            formatted_payload.append({"role": "assistant", "content": str(msg.content)})

    return formatted_payload
