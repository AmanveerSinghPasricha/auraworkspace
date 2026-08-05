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
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine

from app.state import GraphState

logger = logging.getLogger("pii_guardrail")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Explicitly configure Presidio to use the lightweight spaCy model (en_core_web_sm)
provider = NlpEngineProvider(nlp_configuration={
    "nlp_engine_name": "spacy",
    "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
})

nlp_engine = provider.create_engine()

# Initialize Presidio Engines once at startup with small model engine
analyzer_engine = AnalyzerEngine(nlp_engine=nlp_engine)
anonymizer_engine = AnonymizerEngine()

# Target entities to redact (EMAIL_ADDRESS is intentionally excluded so EMAIL_AGENT gets intact target recipients)
ALLOWED_PII_ENTITIES = [
    "PHONE_NUMBER",
    "CREDIT_CARD",
    "US_SSN",
    "IP_ADDRESS",
    "IBAN_CODE",
    "PERSON",
    "LOCATION",
    "ORGANIZATION",
    # "EMAIL_ADDRESS"  # <-- Excluded to allow active email workflows to function properly
]


async def pii_redaction_node(state: GraphState) -> Dict[str, Any]:
    """
    Pre-Graph Middleware Node using Microsoft Presidio.
    Analyzes incoming HumanMessage, redacts sensitive PII entities, and updates graph state cleanly.
    """
    logger.info("🛡️ [PII GUARDRAIL] Running Presidio Engine...")

    # Extract messages safely whether state is a dict or GraphState object
    messages = state.get("messages", []) if isinstance(state, dict) else getattr(state, "messages", [])

    if not messages:
        return {"validation_errors": ["No messages found in state for security evaluation."]}

    latest_msg = messages[-1]
    if not isinstance(latest_msg, HumanMessage):
        return {}  # Proceed if not direct human prompt

    raw_text = str(latest_msg.content)

    # 1. Analyze for specific PII entities (excluding EMAIL_ADDRESS)
    analyzer_results = analyzer_engine.analyze(
        text=raw_text,
        language="en",
        entities=ALLOWED_PII_ENTITIES,
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

    # Extract staged_action_payload safely
    staged_payload = state.get("staged_action_payload") if isinstance(state, dict) else getattr(state, "staged_action_payload", {})

    return {
        "messages": output_messages,
        "staged_action_payload": {
            **(staged_payload or {}),
            "resolved_query": clean_text,
        },
        "validation_errors": []
    }