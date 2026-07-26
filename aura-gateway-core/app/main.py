"""
Aura Gateway Core - Primary FastAPI Gateway Server
==================================================
Exposes REST and Streaming API endpoints for the multi-agent state graph.
Handles lifecycle events for Neon Postgres database connection pooling,
checkpointer initialization, and thread-scoped execution.
"""

import logging
import json
from contextlib import asynccontextmanager
from typing import Dict, Any, List, Optional, AsyncGenerator

from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage

from app.config import settings
from app.database import get_db_pool, close_db_pool
from app.graph import create_aura_graph
from app.state import GraphState, UserProfileContext

logger = logging.getLogger("aura_main")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Global Compiled Graph Application & Persistence Objects
compiled_aura_graph = None


# =====================================================================
# 1. LIFECYCLE MANAGEMENT (STARTUP / SHUTDOWN)
# =====================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manages database pool initialization and LangGraph state graph compilation on startup.
    Ensures safe resource cleanup on shutdown.
    """
    global compiled_aura_graph
    logger.info("🚀 [GATEWAY STARTUP] Initializing Aura Gateway Core server...")

    try:
        # Initialize Neon Postgres connection pool
        pool = await get_db_pool()
        logger.info("✅ [DATABASE] Database connection pool established successfully.")

        # Compile the master state graph
        compiled_aura_graph = create_aura_graph(checkpointer=None, store=None)
        logger.info("✅ [GRAPH LOADED] Master LangGraph engine ready for requests.")

    except Exception as exc:
        logger.error(f"❌ [STARTUP ERROR] Failed to initialize resources: {exc}")
        # Compile fallback graph for local execution/testing
        compiled_aura_graph = create_aura_graph()

    yield

    logger.info("🛑 [GATEWAY SHUTDOWN] Cleaning up database connection pool...")
    await close_db_pool()


# =====================================================================
# 2. FASTAPI APPLICATION SETUP
# =====================================================================
app = FastAPI(
    title="Aura Gateway Core API",
    description="Enterprise Multi-Agent LLM Gateway & Execution Engine built with LangGraph and LiteLLM.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS Middleware Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =====================================================================
# 3. REQUEST / RESPONSE SCHEMAS
# =====================================================================
class ChatRequestPayload(BaseModel):
    user_id: str = Field(default="user_default", description="Unique ID of the requesting user")
    thread_id: str = Field(default="thread_demo_001", description="Session thread ID for conversation scoping")
    message: str = Field(..., description="User prompt or query string")
    department: Optional[str] = Field(default="Engineering", description="User department context")
    role_title: Optional[str] = Field(default="Machine Learning Engineer", description="User professional title")
    preferred_language: Optional[str] = Field(default="English", description="Target response language")


class ChatResponsePayload(BaseModel):
    thread_id: str
    active_route: str
    response: str
    pii_redacted: bool = False
    validation_errors: List[str] = Field(default_factory=list)


# =====================================================================
# 4. SSE STREAMING GENERATOR
# =====================================================================
async def event_stream_generator(payload: ChatRequestPayload) -> AsyncGenerator[str, None]:
    """
    Intercepts LangGraph execution events and streams SSE tokens, node transitions,
    and completion signals in real-time back to the client.
    """
    if not compiled_aura_graph:
        yield f"data: {json.dumps({'type': 'error', 'message': 'Graph engine is uninitialized.'})}\n\n"
        return

    logger.info(f"🌊 [STREAM] Initiating event stream for thread '{payload.thread_id}'...")

    user_context = UserProfileContext(
        user_id=payload.user_id,
        department=payload.department,
        role_title=payload.role_title,
        preferred_language=payload.preferred_language,
    )

    initial_state = {
        "messages": [HumanMessage(content=payload.message)],
        "user_context": user_context,
        "staged_action_payload": {"resolved_query": payload.message, "raw_text": payload.message},
    }

    config = {"configurable": {"thread_id": payload.thread_id}}

    try:
        # Stream events directly from compiled LangGraph instance
        async for event in compiled_aura_graph.astream_events(initial_state, config=config, version="v2"):
            kind = event.get("event")
            node_name = event.get("name", "")

            # 1. Yield node transition events
            if kind == "on_chain_start" and node_name in ["pii_redaction", "supervisor_router", "general_agent", "rag_engine", "data_extractor"]:
                yield f"data: {json.dumps({'type': 'node_start', 'node': node_name})}\n\n"

            # 2. Yield individual token delta chunks from active LLMs
            elif kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    yield f"data: {json.dumps({'type': 'token', 'content': str(chunk.content), 'node': node_name})}\n\n"

        # 3. Final completion handshake signal
        yield f"data: {json.dumps({'type': 'done', 'thread_id': payload.thread_id})}\n\n"

    except Exception as exc:
        logger.error(f"❌ [STREAM ERROR] Execution streaming failed: {exc}")
        yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"


# =====================================================================
# 5. API ENDPOINTS
# =====================================================================
@app.get("/", tags=["System"])
async def root_status():
    """
    Root status endpoint providing basic server metadata and documentation links.
    """
    return {
        "service": getattr(settings, "APP_NAME", "Aura Gateway Core"),
        "status": "online",
        "docs": "/docs",
        "health": "/health"
    }


@app.get("/health", tags=["System"])
async def health_check():
    """
    Returns live gateway status and real-time health diagnostics
    by testing active database ping and graph compilation state.
    """
    db_healthy = False
    try:
        pool = await get_db_pool()
        # psycopg_pool uses .connection() context manager
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1;")
                db_healthy = True
    except Exception as exc:
        logger.error(f"❌ [HEALTH CHECK] Database ping failed: {exc}")

    is_healthy = (compiled_aura_graph is not None) and db_healthy

    return {
        "status": "healthy" if is_healthy else "unhealthy",
        "service": getattr(settings, "APP_NAME", "Aura Gateway Core"),
        "version": app.version,
        "diagnostics": {
            "graph_compiled": compiled_aura_graph is not None,
            "database_connected": db_healthy,
        }
    }


@app.post("/api/v1/chat", response_model=ChatResponsePayload, tags=["Execution Engine"])
async def execute_chat_query(payload: ChatRequestPayload):
    """
    Primary REST endpoint to process user queries through the LangGraph engine.
    Applies PII redaction, intent routing, dynamic personas, and node execution.
    """
    if not compiled_aura_graph:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="State graph engine is not initialized.",
        )

    logger.info(f"📩 [REQUEST] Processing query for thread '{payload.thread_id}' from user '{payload.user_id}'...")

    # Build UserProfileContext
    user_context = UserProfileContext(
        user_id=payload.user_id,
        department=payload.department,
        role_title=payload.role_title,
        preferred_language=payload.preferred_language,
    )

    # Construct initial state input
    initial_state = {
        "messages": [HumanMessage(content=payload.message)],
        "user_context": user_context,
        "staged_action_payload": {"resolved_query": payload.message, "raw_text": payload.message},
    }

    # Configuration thread scope
    config = {"configurable": {"thread_id": payload.thread_id}}

    try:
        # Execute compiled graph workflow
        final_state = await compiled_aura_graph.ainvoke(initial_state, config=config)

        # Extract latest message response from state
        response_text = "No response generated."
        if final_state.get("messages"):
            response_text = str(final_state["messages"][-1].content)

        active_route = "GENERAL_AGENT"
        if final_state.get("router_state") and hasattr(final_state["router_state"], "active_route"):
            active_route = final_state["router_state"].active_route

        pii_was_redacted = False
        staged_payload = final_state.get("staged_action_payload") or {}
        if staged_payload.get("pii_redacted_map"):
            pii_was_redacted = True

        return ChatResponsePayload(
            thread_id=payload.thread_id,
            active_route=active_route,
            response=response_text,
            pii_redacted=pii_was_redacted,
            validation_errors=final_state.get("validation_errors", []),
        )

    except Exception as exc:
        logger.error(f"❌ [GATEWAY EXECUTION ERROR] Workflow execution failed: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Execution engine failure: {str(exc)}",
        )


@app.post("/api/v1/chat/stream", tags=["Execution Engine"])
async def execute_chat_query_stream(payload: ChatRequestPayload):
    """
    Real-time Server-Sent Events (SSE) streaming endpoint.
    Yields LLM tokens, node start events, and completion signals in real-time.
    """
    return StreamingResponse(
        event_stream_generator(payload),
        media_type="text/event-stream"
    )