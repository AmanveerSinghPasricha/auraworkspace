"""
Aura Gateway Core - Master LangGraph Workflow Assembly
======================================================
Compiles the complete multi-agent state graph including:
1. Pre-Graph Security & PII Redaction
2. Supervisor Router
3. RAG Engine, General Agent, Data Extractor, Email/HITL Agent, and GitHub MCP Agent
"""

import logging
from typing import Dict, Any, Literal
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres.aio import AsyncPostgresStore

from app.state import GraphState
from app.nodes.pii_security import pii_redaction_node
from app.nodes.router import supervisor_router_node
from app.nodes.rag import rag_node
from app.nodes.general import general_agent_node
from app.nodes.extractor import data_extractor_node
from app.nodes.email_agent_node import email_dispatch_node
from app.nodes.github_agent_node import github_dispatch_node

logger = logging.getLogger("aura_graph")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


# =====================================================================
# 1. CONDITIONAL ROUTING EDGE EVALUATOR
# =====================================================================
def route_next_action(state: GraphState) -> Literal["rag_engine", "general_agent", "data_extractor", "email_agent", "github_agent", "__end__"]:
    """
    Evaluates intent classification and directs execution to the designated node.
    Safely extracts router decisions whether state attributes or dict keys are used.
    """
    # Check for validation errors (supports dict or object state)
    validation_errors = getattr(state, "validation_errors", None) or (state.get("validation_errors") if isinstance(state, dict) else None)
    if validation_errors:
        logger.warning(f"⚠️ [GRAPH ROUTER] Validation errors detected. Terminating flow: {validation_errors}")
        return END

    # Safe extraction of router_state
    router_state = getattr(state, "router_state", None) or (state.get("router_state") if isinstance(state, dict) else None)
    
    selected_route = "GENERAL_AGENT"
    if router_state:
        if isinstance(router_state, dict):
            selected_route = router_state.get("active_route", "GENERAL_AGENT")
        else:
            selected_route = getattr(router_state, "active_route", "GENERAL_AGENT")

    # Normalize to uppercase string
    selected_route_str = str(selected_route).upper()

    if selected_route_str in ["RAG_ENGINE", "RAG_TREE"]:
        logger.info("🔀 [GRAPH ROUTE] Driving execution to -> rag_engine")
        return "rag_engine"
    elif selected_route_str in ["DATA_EXTRACTOR", "EXTRACTOR"]:
        logger.info("🔀 [GRAPH ROUTE] Driving execution to -> data_extractor")
        return "data_extractor"
    elif selected_route_str in ["EMAIL_AGENT", "SEND_EMAIL"]:
        logger.info("🔀 [GRAPH ROUTE] Driving execution to -> email_agent")
        return "email_agent"
    elif selected_route_str in ["GITHUB_AGENT", "GITHUB"]:
        logger.info("🔀 [GRAPH ROUTE] Driving execution to -> github_agent")
        return "github_agent"
    else:
        logger.info(f"🔀 [GRAPH ROUTE] Driving execution to -> general_agent (Selected route: '{selected_route_str}')")
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
    logger.info("🛠️ [GRAPH BUILD] Assembling state graph workflow...")

    # Initialize StateGraph with central GraphState schema
    workflow = StateGraph(GraphState)

    # 1. Add Processing Nodes
    workflow.add_node("pii_redaction", pii_redaction_node)
    workflow.add_node("supervisor_router", supervisor_router_node)
    workflow.add_node("rag_engine", rag_node)
    workflow.add_node("general_agent", general_agent_node)
    workflow.add_node("data_extractor", data_extractor_node)
    workflow.add_node("email_agent", email_dispatch_node)
    workflow.add_node("github_agent", github_dispatch_node)

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
            "email_agent": "email_agent",
            "github_agent": "github_agent",
            END: END
        }
    )

    # 4. Terminal Edges back to END
    workflow.add_edge("rag_engine", END)
    workflow.add_edge("general_agent", END)
    workflow.add_edge("data_extractor", END)
    workflow.add_edge("email_agent", END)
    workflow.add_edge("github_agent", END)

    # 5. Compile StateGraph with Checkpointer & Store
    compiled_app = workflow.compile(
        checkpointer=checkpointer,
        store=store
    )

    logger.info("✅ [GRAPH BUILD] Aura Workspace State Graph compiled successfully!")
    return compiled_app