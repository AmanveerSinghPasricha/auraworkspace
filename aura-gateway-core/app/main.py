"""
Aura Gateway Core - Primary FastAPI Gateway Server
==================================================
Exposes REST, Streaming, and Ingestion API endpoints for the multi-agent state graph.
Handles lifecycle events for Neon Postgres database connection pooling,
checkpointer initialization, thread-scoped execution, and async document processing.
"""

import os
import shutil
import logging
import json
import uuid
import uvicorn
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Dict, Any, List, Optional, AsyncGenerator

from fastapi import FastAPI, HTTPException, Depends, status, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage

from app.config import settings
from app.database import get_db_pool, close_db_pool
from app.state import GraphState, UserProfileContext

logger = logging.getLogger("aura_main")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Directory setup for file uploads
UPLOAD_DIR = Path("./uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Global Compiled Graph Application & Background Job Store
compiled_aura_graph = None
ingestion_jobs: Dict[str, Dict[str, Any]] = {}


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

        # Lazy import graph builder to defer heavy ML package loading until after DB init
        from app.graph import create_aura_graph
        compiled_aura_graph = create_aura_graph(checkpointer=None, store=None)
        logger.info("✅ [GRAPH LOADED] Master LangGraph engine ready for requests.")

    except Exception as exc:
        logger.error(f"❌ [STARTUP ERROR] Failed to initialize resources: {exc}")
        from app.graph import create_aura_graph
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
    file_hash: Optional[str] = Field(default=None, description="Active RAG document hash")
    document_ref: Optional[str] = Field(default=None, description="Active RAG document path or reference")


class ChatResponsePayload(BaseModel):
    thread_id: str
    active_route: str
    response: str
    pii_redacted: bool = False
    validation_errors: List[str] = Field(default_factory=list)


# =====================================================================
# 4. ASYNCHRONOUS INGESTION WORKER
# =====================================================================
async def process_document_background_task(job_id: str, file_path: Path, filename: str):
    """Processes document parsing and node summary generation asynchronously to prevent HTTP timeouts."""
    from app.nodes.rag import _vectorless_engine_instance

    try:
        ingestion_jobs[job_id]["status"] = "processing"
        file_hash = _vectorless_engine_instance.compute_file_hash(str(file_path))

        root_tree = _vectorless_engine_instance.load_tree_from_cache(file_hash)
        if not root_tree:
            root_tree = _vectorless_engine_instance.parse_file_to_tree(str(file_path))
            await _vectorless_engine_instance.generate_node_summaries(root_tree)
            _vectorless_engine_instance.save_tree_to_cache(file_hash, root_tree)

        ingestion_jobs[job_id]["status"] = "completed"
        ingestion_jobs[job_id]["result"] = {
            "filename": filename,
            "file_path": str(file_path),
            "file_hash": file_hash,
            "chapters_detected": len(root_tree.children) if root_tree else 0,
            "document_ref": str(file_path)
        }
        logger.info(f"✅ [ASYNC INGESTION] Document '{filename}' successfully indexed.")

    except Exception as exc:
        logger.error(f"❌ [ASYNC INGESTION ERROR] Failed for '{filename}': {exc}")
        ingestion_jobs[job_id]["status"] = "failed"
        ingestion_jobs[job_id]["error"] = str(exc)


# =====================================================================
# 5. SSE STREAMING GENERATOR
# =====================================================================
async def event_stream_generator(payload: ChatRequestPayload) -> AsyncGenerator[str, None]:
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
        "staged_action_payload": {
            "resolved_query": payload.message, 
            "raw_text": payload.message,
            "file_hash": payload.file_hash,
            "document_ref": payload.document_ref,
        },
    }

    config = {"configurable": {"thread_id": payload.thread_id}}

    try:
        async for event in compiled_aura_graph.astream_events(initial_state, config=config, version="v2"):
            kind = event.get("event")
            node_name = event.get("name", "")

            if kind == "on_chain_start" and node_name in ["pii_redaction", "supervisor_router", "general_agent", "rag_engine", "data_extractor"]:
                yield f"data: {json.dumps({'type': 'node_start', 'node': node_name})}\n\n"

            elif kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    yield f"data: {json.dumps({'type': 'token', 'content': str(chunk.content), 'node': node_name})}\n\n"

        yield f"data: {json.dumps({'type': 'done', 'thread_id': payload.thread_id})}\n\n"

    except Exception as exc:
        logger.error(f"❌ [STREAM ERROR] Execution streaming failed: {exc}")
        yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"


# =====================================================================
# 6. API ENDPOINTS
# =====================================================================
@app.get("/", tags=["System"])
async def root_status():
    return {
        "service": getattr(settings, "APP_NAME", "Aura Gateway Core"),
        "status": "online",
        "docs": "/docs",
        "health": "/health"
    }


@app.get("/health", tags=["System"])
async def health_check():
    db_healthy = False
    try:
        pool = await get_db_pool()
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
    if not compiled_aura_graph:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="State graph engine is not initialized.",
        )

    logger.info(f"📩 [REQUEST] Processing query for thread '{payload.thread_id}' from user '{payload.user_id}'...")

    user_context = UserProfileContext(
        user_id=payload.user_id,
        department=payload.department,
        role_title=payload.role_title,
        preferred_language=payload.preferred_language,
    )

    initial_state = {
        "messages": [HumanMessage(content=payload.message)],
        "user_context": user_context,
        "staged_action_payload": {
            "resolved_query": payload.message, 
            "raw_text": payload.message,
            "file_hash": payload.file_hash,
            "document_ref": payload.document_ref,
        },
    }

    config = {"configurable": {"thread_id": payload.thread_id}}

    try:
        final_state = await compiled_aura_graph.ainvoke(initial_state, config=config)

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
    return StreamingResponse(
        event_stream_generator(payload),
        media_type="text/event-stream"
    )


@app.post("/api/v1/documents/upload", tags=["Ingestion Engine"])
async def upload_document_endpoint(
    background_tasks: BackgroundTasks, 
    file: UploadFile = File(...)
):
    allowed_extensions = {".pdf", ".docx", ".xlsx", ".pptx", ".txt"}
    file_ext = Path(file.filename).suffix.lower()

    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format '{file_ext}'. Allowed formats: {list(allowed_extensions)}"
        )

    saved_file_path = UPLOAD_DIR / file.filename
    job_id = str(uuid.uuid4())

    try:
        with saved_file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        ingestion_jobs[job_id] = {
            "status": "queued",
            "filename": file.filename,
            "job_id": job_id
        }

        # Dispatch heavy indexing to background task
        background_tasks.add_task(
            process_document_background_task, 
            job_id, 
            saved_file_path, 
            file.filename
        )

        return {
            "status": "queued",
            "job_id": job_id,
            "filename": file.filename,
            "message": "Document upload received. Background ingestion initialized."
        }

    except Exception as exc:
        logger.error(f"❌ [UPLOAD ERROR] Failed to save file '{file.filename}': {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save document: {str(exc)}"
        )


@app.get("/api/v1/documents/status/{job_id}", tags=["Ingestion Engine"])
async def get_ingestion_job_status(job_id: str):
    """Allows frontend to poll the background document ingestion status."""
    if job_id not in ingestion_jobs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ingestion job ID not found."
        )
    return ingestion_jobs[job_id]


# =====================================================================
# 7. DIRECT SERVER ENTRYPOINT (PROD / RENDER BINDING)
# =====================================================================
if __name__ == "__main__":
    server_port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app.main:app", host="0.0.0.0", port=server_port, reload=False)