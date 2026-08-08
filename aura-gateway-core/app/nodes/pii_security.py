"""
Aura Gateway Core - Pre-Graph PII Redaction Node (Presidio)
==========================================================
Middleware using Microsoft Presidio for ML + Regex hybrid PII redaction.
Sanitizes sensitive entities before messages propagate through the graph.
"""

import logging
import threading
from typing import Dict, Any, List, Tuple
from langchain_core.messages import HumanMessage, BaseMessage, RemoveMessage

from app.state import GraphState

logger = logging.getLogger("pii_guardrail")

# Global singleton caches for lazy initialization
_analyzer_engine = None
_anonymizer_engine = None
_engine_lock = threading.Lock()

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


def get_presidio_engines() -> Tuple[Any, Any]:
    """
    Lazy-loads Microsoft Presidio and spaCy NLP engines on first use.
    Prevents heavy ML models from loading into RAM during app startup (avoids Exit 137 OOM).
    """
    global _analyzer_engine, _anonymizer_engine

    if _analyzer_engine is None or _anonymizer_engine is None:
        with _engine_lock:
            if _analyzer_engine is None or _anonymizer_engine is None:
                logger.info("🛡️ [PII GUARDRAIL] Lazy-loading Presidio & spaCy (en_core_web_sm)...")
                from presidio_analyzer import AnalyzerEngine
                from presidio_analyzer.nlp_engine import NlpEngineProvider
                from presidio_anonymizer import AnonymizerEngine

                provider = NlpEngineProvider(nlp_configuration={
                    "nlp_engine_name": "spacy",
                    "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
                })
                nlp_engine = provider.create_engine()
                _analyzer_engine = AnalyzerEngine(nlp_engine=nlp_engine)
                _anonymizer_engine = AnonymizerEngine()
                logger.info("✅ [PII GUARDRAIL] Presidio engines initialized successfully.")

    return _analyzer_engine, _anonymizer_engine


async def pii_redaction_node(state: GraphState) -> Dict[str, Any]:
    """
    Pre-Graph Middleware Node using Microsoft Presidio.
    Analyzes incoming HumanMessage, redacts sensitive PII entities, and updates graph state cleanly.
    """
    # Extract messages safely whether state is a dict or GraphState object
    messages = state.get("messages", []) if isinstance(state, dict) else getattr(state, "messages", [])

    if not messages:
        return {"validation_errors": ["No messages found in state for security evaluation."]}

    latest_msg = messages[-1]
    if not isinstance(latest_msg, HumanMessage):
        return {}  # Proceed if not direct human prompt

    raw_text = str(latest_msg.content)

    # 1. Lazy load Presidio engines (Only consumes memory when executing this node)
    analyzer, anonymizer = get_presidio_engines()

    logger.info("🛡️ [PII GUARDRAIL] Running Presidio Engine...")

    # 2. Analyze for specific PII entities (excluding EMAIL_ADDRESS)
    analyzer_results = analyzer.analyze(
        text=raw_text,
        language="en",
        entities=ALLOWED_PII_ENTITIES,
    )

    if not analyzer_results:
        return {"validation_errors": []}  # Clean prompt, proceed

    # 3. Anonymize detected entities
    anonymized = anonymizer.anonymize(
        text=raw_text,
        analyzer_results=analyzer_results
    )
    clean_text = anonymized.text

    logger.info(f"🔒 [PII REDACTED] Presidio masked {len(analyzer_results)} sensitive entity/entities.")

    # 4. Safely update message history using RemoveMessage
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