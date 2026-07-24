"""
Aura Gateway Core - Production Data Extraction Node
====================================================
Features:
1. Location-Agnostic Extraction (Robust to missing page numbers or metadata)
2. Type-Safe Structured Data Extraction via Instructor & Gemini 2.5 Flash
3. Pydantic Description-Guided Schema Compliance & Type Coercion
4. Zero-Temperature Determinism & Automatic Self-Healing Retries
5. Immutable FinOps Usage & Cost Accounting
"""

import logging
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
import tiktoken
import instructor
from litellm import acompletion
from langchain_core.messages import AIMessage, BaseMessage, trim_messages

from app.config import settings
from app.state import GraphState

logger = logging.getLogger("extractor_node")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

instructor_client = instructor.from_litellm(acompletion)

try:
    TOKEN_ENCODER = tiktoken.encoding_for_model("gpt-4o")
except Exception:
    TOKEN_ENCODER = tiktoken.get_encoding("cl100k_base")


class KeyValuePair(BaseModel):
    key: str = Field(
        description="Normalized field name in clean snake_case (e.g., peak_demand_mw, total_revenue_usd)."
    )
    value: Any = Field(
        description=(
            "Extracted value (float, int, str, or list). "
            "DO NOT include currency symbols or unit labels if numeric; output clean numbers (e.g., 14500.0, not ',500')."
        )
    )
    confidence_score: float = Field(
        default=1.0, 
        ge=0.0, 
        le=1.0, 
        description="Model confidence rating from 0.0 (uncertain) to 1.0 (exact visual/textual match)."
    )


class ExtractedDataSet(BaseModel):
    dataset_title: str = Field(
        default="extracted_document_dataset", 
        description="Brief summary identifier or title of the extracted entity or table."
    )
    location_found: Optional[str] = Field(
        default="Document Content", 
        description="Where the data was located (e.g., 'Page 12', 'Figure 3', or 'Global Search')."
    )
    data_points: List[KeyValuePair] = Field(
        default_factory=list, 
        description="Array of extracted key-value pairs."
    )
    summary_notes: Optional[str] = Field(
        default=None, 
        description="Key contextual observations or extraction caveats."
    )


def count_tokens_exact(messages: List[BaseMessage]) -> int:
    total = 0
    for msg in messages:
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        total += len(TOKEN_ENCODER.encode(content))
    return total


def prepare_extraction_payload(
    messages: List[BaseMessage], 
    system_prompt: str, 
    max_tokens: int = 4000
) -> List[dict]:
    payload = [{"role": "system", "content": system_prompt}]
    
    if not messages:
        return payload

    trimmed = trim_messages(
        messages,
        max_tokens=max_tokens,
        token_counter=count_tokens_exact,
        strategy="last",
        start_on="human",
        include_system=False,
        allow_partial=False,
    )

    for msg in trimmed:
        if msg.type == "human":
            payload.append({"role": "user", "content": str(msg.content)})
        elif msg.type == "ai":
            payload.append({"role": "assistant", "content": str(msg.content)})

    return payload


async def data_extractor_node(state: GraphState) -> Dict[str, Any]:
    logger.info("?? [EXTRACTOR NODE] Executing resilient extraction pipeline...")

    raw_prompt = ""
    if state.staged_action_payload and state.staged_action_payload.get("resolved_query"):
        raw_prompt = state.staged_action_payload["resolved_query"]
    elif state.messages:
        raw_prompt = str(state.messages[-1].content)

    if not raw_prompt:
        return {
            "messages": [AIMessage(content="No valid content provided for structured extraction.")],
            "validation_errors": ["Empty payload in data_extractor_node."]
        }

    system_prompt = (
        "You are Aura Workspace's Automated Data & Visual Extraction Engine.\n"
        "Your goal is to parse tables, metrics, matrix data, or visual figures into a structured dataset.\n\n"
        "### EXTRACTION & LOCATION RULES:\n"
        "1. SPECIFIC LOCATION: If the user provides a page number, figure label, or section header (e.g., 'Page 12', 'Figure 3'), prioritize extracting data from that location.\n"
        "2. MISSING LOCATION FALLBACK: If NO page number or location is provided:\n"
        "   - Search the entire document context for tables, charts, or structural figures that match the user's topic.\n"
        "   - Extract ALL high-confidence tabular or structured data points matching the query intent.\n"
        "3. NEVER FAIL ON MISSING METADATA: Do not fail or abort simply because page numbers or document titles are absent.\n"
        "4. DATA NORMALIZATION: Normalize all keys into clean snake_case. Convert numeric strings into clean floats or ints without currency/unit symbols."
    )

    llm_payload = prepare_extraction_payload(
        messages=state.messages,
        system_prompt=system_prompt,
        max_tokens=4000
    )

    try:
        extractor_model = getattr(
            settings, 
            "LLM_EXTRACTOR_PRIMARY", 
            getattr(settings, "LLM_RAG_PRIMARY", settings.LLM_GENERAL_PRIMARY)
        )
        fallbacks_list = [settings.LLM_RAG_FALLBACK] if hasattr(settings, "LLM_RAG_FALLBACK") else None

        extracted_data, raw_completion = await instructor_client.chat.completions.create_with_completion(
            model=extractor_model,
            response_model=ExtractedDataSet,
            messages=llm_payload,
            temperature=0.0,
            max_retries=2,
            fallbacks=fallbacks_list,
        )

        parsed_dict = extracted_data.model_dump()
        
        table_rows = [
            f"| **{dp['key']}** | {dp['value']} | {int(dp['confidence_score'] * 100)}% |" 
            for dp in parsed_dict["data_points"]
        ]
        
        markdown_table = (
            f"### ?? Extracted Dataset: {parsed_dict['dataset_title']}\n"
            f"**Source Location:** {parsed_dict['location_found']}\n\n"
            "| Field Key | Extracted Value | Confidence |\n"
            "| :--- | :--- | :--- |\n" + "\n".join(table_rows)
        )
        if parsed_dict.get("summary_notes"):
            markdown_table += f"\n\n**Notes:** {parsed_dict['summary_notes']}"

        new_finops_ledger = state.finops_ledger.model_copy(deep=True)
        if hasattr(raw_completion, "usage") and raw_completion.usage:
            usage = raw_completion.usage
            new_finops_ledger.log_transaction_usage(
                model_response_metadata={
                    "prompt_tokens": getattr(usage, "prompt_tokens", 0),
                    "completion_tokens": getattr(usage, "completion_tokens", 0),
                },
                model_pricing_rates={"in": 0.0, "cached": 0.0, "out": 0.0},
            )

        logger.info(
            f"? [EXTRACTOR SUCCESS] Extracted {len(parsed_dict['data_points'])} items "
            f"from '{parsed_dict['location_found']}'."
        )

        return {
            "messages": [AIMessage(content=markdown_table)],
            "extracted_data_matrix": parsed_dict,
            "finops_ledger": new_finops_ledger,
            "validation_errors": []
        }

    except Exception as exc:
        logger.error(f"? [EXTRACTOR ERROR] Structured extraction failed: {exc}")
        return {
            "messages": [AIMessage(content="Failed to extract structured data from the provided input.")],
            "validation_errors": [str(exc)]
        }
