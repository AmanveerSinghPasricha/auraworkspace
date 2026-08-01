"""
Aura Gateway Core - Supervisor Router Node Unit Test Suite
==========================================================
Tests semantic intent classification across various query types and 
state contexts without needing the FastAPI HTTP layer.
"""

import sys
import asyncio
import logging
from pathlib import Path

# Ensure root directory is on Python path
sys.path.append(str(Path(__file__).parent.parent))

from langchain_core.messages import HumanMessage, AIMessage
from app.nodes.router import supervisor_router_node
from app.state import GraphState

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("test_router")


async def run_router_tests():
    print("\n" + "=" * 70)
    print("🧪 [TEST SUITE] STARTING SUPERVISOR INTENT ROUTER TEST")
    print("=" * 70 + "\n")

    test_cases = [
        {
            "name": "1. Exact Document & Section Query",
            "state": {
                "messages": [
                    HumanMessage(content="According to NIST.SP.800-53r5.pdf, what are the specific requirements for account management described in AC-2?")
                ],
                "staged_action_payload": {},
                "router_state": {}
            },
            "expected_route": "RAG_ENGINE"
        },
        {
            "name": "2. Paraphrased Policy Query (No Filename Mentioned)",
            "state": {
                "messages": [
                    HumanMessage(content="What are our organization's rules regarding emergency account deactivation and offboarding?")
                ],
                "staged_action_payload": {"document_ref": "uploads/NIST.SP.800-53r5.pdf"},
                "router_state": {"last_document_ref": "uploads/NIST.SP.800-53r5.pdf"}
            },
            "expected_route": "RAG_ENGINE"
        },
        {
            "name": "3. Multi-Turn Response to Disambiguation Prompt",
            "state": {
                "messages": [
                    AIMessage(content="You have multiple documents uploaded. Please specify which document you'd like to query:\n- NIST.SP.800-53r5.pdf\n- doc.txt"),
                    HumanMessage(content="NIST.SP.800-53r5.pdf use this file")
                ],
                "staged_action_payload": {},
                "router_state": {}
            },
            "expected_route": "RAG_ENGINE"
        },
        {
            "name": "4. Explicit Matrix / JSON Extraction Request",
            "state": {
                "messages": [
                    HumanMessage(content="Extract all access control metrics from this text and convert them into a structured JSON matrix format.")
                ],
                "staged_action_payload": {},
                "router_state": {}
            },
            "expected_route": "EXTRACTOR"
        },
        {
            "name": "5. General Conversational / Non-Document Chat",
            "state": {
                "messages": [
                    HumanMessage(content="Hello! Can you help me write a Python script to calculate Fibonacci numbers?")
                ],
                "staged_action_payload": {},
                "router_state": {}
            },
            "expected_route": "GENERAL_AGENT"
        }
    ]

    passed_count = 0

    for test in test_cases:
        print("-" * 70)
        print(f"📌 Running Test: {test['name']}")
        print(f"💬 Latest Query: '{test['state']['messages'][-1].content}'")

        try:
            result = await supervisor_router_node(test["state"])
            router_output = result.get("router_state", {})
            assigned_route = router_output.get("active_route")
            reasoning = router_output.get("reasoning", "No reasoning provided")
            confidence = router_output.get("confidence", 0.0)

            print(f"🎯 Assigned Route: {assigned_route}")
            print(f"📊 Confidence Score: {confidence}")
            print(f"💡 Reasoning: {reasoning}")

            if assigned_route == test["expected_route"]:
                print("✅ PASSED")
                passed_count += 1
            else:
                print(f"❌ FAILED - Expected '{test['expected_route']}', but got '{assigned_route}'")

        except Exception as exc:
            print(f"💥 EXCEPTION: {exc}")

        print("-" * 70 + "\n")

    print("=" * 70)
    print(f"🏆 TEST SUMMARY: {passed_count}/{len(test_cases)} Tests Passed")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    asyncio.run(run_router_tests())