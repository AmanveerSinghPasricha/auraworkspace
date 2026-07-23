"""
Aura Gateway Core - Pre-Graph PII Redaction Node (Presidio)
==========================================================
Middleware using Microsoft Presidio for ML + Regex hybrid PII redaction.
Sanitizes sensitive entities before messages propagate through the graph.
"""

import logging
from typing import Dict, Any, List
from langchain_core.messages import HumanMessage, BaseMessage, RemoveMessage
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine

from app.state import GraphState

logger = logging.getLogger("pii_guardrail")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Initialize Presidio Engines once at startup
analyzer_engine = AnalyzerEngine()
anonymizer_engine = AnonymizerEngine()


async def pii_redaction_node(state: GraphState) -> Dict[str, Any]:
    """
    Pre-Graph Middleware Node using Microsoft Presidio.
    Analyzes incoming HumanMessage, redacts sensitive PII entities (Names, Emails,
    Phone Numbers, Credit Cards, SSNs), and updates graph state cleanly.
    """
    logger.info("🛡️ [PII GUARDRAIL] Running Presidio Engine...")

    if not state.messages:
        return {"validation_errors": ["No messages found in state for security evaluation."]}

    latest_msg = state.messages[-1]
    if not isinstance(latest_msg, HumanMessage):
        return {}  # Proceed if not direct human prompt

    raw_text = str(latest_msg.content)

    # 1. Analyze for PII entities
    analyzer_results = analyzer_engine.analyze(
        text=raw_text,
        language="en",
    )

    if not analyzer_results:
        return {"validation_errors": []}  # Clean prompt, proceed

    # 2. Anonymize detected entities
    anonymized = anonymizer_engine.anonymize(
        text=raw_text,
        analyzer_results=analyzer_results
    )
    clean_text = anonymized.text

    logger.info(f"🔒 [PII REDACTED] Presidio masked {len(analyzer_results)} sensitive entity/entities.")

    # 3. Safely update message history using RemoveMessage
    output_messages: List[BaseMessage] = []
    if hasattr(latest_msg, "id") and latest_msg.id:
        output_messages.append(RemoveMessage(id=latest_msg.id))

    output_messages.append(HumanMessage(content=clean_text))

    return {
        "messages": output_messages,
        "staged_action_payload": {
            **(state.staged_action_payload or {}),
            "resolved_query": clean_text,
        },
        "validation_errors": []
    }