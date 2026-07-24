"""
Aura Gateway Core - Master LangGraph Workflow Assembly
======================================================
Compiles the complete multi-agent state graph connecting:
1. Pre-Graph Security & PII Redaction Middleware (Presidio)
2. Pure-LLM Intent Router Node (Instructor)
3. Vectorless RAG Engine, General Agent, and Structured Data Extractor Branches
4. Neon Postgres State Persistence & Store Integration
"""

import logging
from typing import Dict, Any, Literal
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres.aio import AsyncPostgresStore

from app.state import GraphState
from app.nodes.pii import pii_redaction_node
from app.nodes.router import supervisor_router_node
from app.nodes.rag import rag_node
from app.nodes.general import general_agent_node
from app.nodes.extractor import data_extractor_node

logger = logging.getLogger("aura_graph")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


# =====================================================================
# 1. CONDITIONAL ROUTING EDGE EVALUATOR
# =====================================================================
def route_next_action(state: GraphState) -> Literal["rag_engine", "general_agent", "data_extractor", "__end__"]:
    """
    Evaluates the intent classification state set by supervisor_router_node
    and directs the execution path to the designated node.
    """
    if state.validation_errors:
        logger.warning(f"?? [GRAPH ROUTER] Validation errors detected. Terminating flow: {state.validation_errors}")
        return END

    selected_route = state.router_state.active_route.upper() if state.router_state else "GENERAL_AGENT"

    if selected_route == "RAG_TREE":
        logger.info("?? [GRAPH ROUTE] Driving execution to -> rag_engine")
        return "rag_engine"
    elif selected_route == "EXTRACTOR":
        logger.info("?? [GRAPH ROUTE] Driving execution to -> data_extractor")
        return "data_extractor"
    else:
        logger.info("?? [GRAPH ROUTE] Driving execution to -> general_agent")
        return "general_agent"


# =====================================================================
# 2. GRAPH ASSEMBLY & COMPILATION
# =====================================================================
def create_aura_graph(
    checkpointer: AsyncPostgresSaver = None,
    store: AsyncPostgresStore = None
):
    """
    Constructs and compiles the Aura Gateway Core state graph workflow.
    """
    logger.info("??? [GRAPH BUILD] Assembling state graph workflow...")

    # Initialize StateGraph with central GraphState schema
    workflow = StateGraph(GraphState)

    # 1. Add Processing Nodes
    workflow.add_node("pii_redaction", pii_redaction_node)
    workflow.add_node("supervisor_router", supervisor_router_node)
    workflow.add_node("rag_engine", rag_node)
    workflow.add_node("general_agent", general_agent_node)
    workflow.add_node("data_extractor", data_extractor_node)

    # 2. Define Entry Point & Static Middleware Edges
    workflow.add_edge(START, "pii_redaction")
    workflow.add_edge("pii_redaction", "supervisor_router")

    # 3. Define Dynamic Conditional Routing Edges from Supervisor Router
    workflow.add_conditional_edges(
        "supervisor_router",
        route_next_action,
        {
            "rag_engine": "rag_engine",
            "general_agent": "general_agent",
            "data_extractor": "data_extractor",
            END: END
        }
    )

    # 4. Terminal Edges back to END
    workflow.add_edge("rag_engine", END)
    workflow.add_edge("general_agent", END)
    workflow.add_edge("data_extractor", END)

    # 5. Compile StateGraph with Checkpointer & Store
    compiled_app = workflow.compile(
        checkpointer=checkpointer,
        store=store
    )

    logger.info("? [GRAPH BUILD] Aura Workspace State Graph compiled successfully!")
    return compiled_app
