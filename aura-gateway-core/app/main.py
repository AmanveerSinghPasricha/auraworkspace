"""
Aura Gateway Core - Primary FastAPI Gateway Server
==================================================
Exposes REST, Streaming, Ingestion, and Phase 4 Auth & Memory API endpoints
for the multi-agent state graph. Handles lifecycle events for Neon Postgres database
connection pooling, checkpointer initialization, thread-scoped execution,
and async document processing.
"""

import os
import json
import uuid
import logging
import uvicorn
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Dict, Any, List, Optional, AsyncGenerator

from fastapi import FastAPI, HTTPException, Depends, status, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage
from langgraph.types import Command
from sqlalchemy.future import select

from app.config import settings
from app.database import get_db_pool, close_db_pool
from app.db import engine, Base, AsyncSessionLocal
from app.models.user import User
from app.routers.auth import router as auth_router
try:
    from app.routers.github_auth import router as github_auth_router
except ImportError:
    github_auth_router = None

from app.state import GraphState, UserProfileContext

os.environ["MALLOC_TRIM_THRESHOLD_"] = "65536"
os.environ["OMP_NUM_THREADS"] = "2"

logger = logging.getLogger("aura_main")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

UPLOAD_DIR = Path("./uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

compiled_aura_graph = None
ingestion_jobs: Dict[str, Dict[str, Any]] = {}


# =====================================================================
# 1. LIFECYCLE MANAGEMENT (STARTUP / SHUTDOWN)
# =====================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manages database pool initialization, ORM table creation, and LangGraph
    state graph compilation on startup. Ensures safe resource cleanup on shutdown.
    """
    global compiled_aura_graph
    logger.info("🚀 [GATEWAY STARTUP] Initializing Aura Gateway Core server...")

    try:
        pool = await get_db_pool()
        logger.info("✅ [DATABASE] Database connection pool established successfully.")

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("✅ [DATABASE ORM] Database schema models verified & created.")

        from app.graph import create_aura_graph
        compiled_aura_graph = create_aura_graph(checkpointer=None, store=None)
        logger.info("✅ [GRAPH LOADED] Master LangGraph engine ready for requests.")

    except Exception as exc:
        logger.error(f"❌ [STARTUP ERROR] Failed to initialize resources: {exc}")
        if compiled_aura_graph is None:
            from app.graph import create_aura_graph
            compiled_aura_graph = create_aura_graph(checkpointer=None, store=None)

    yield

    logger.info("🛑 [GATEWAY SHUTDOWN] Cleaning up database connection pool...")
    await close_db_pool()


# =====================================================================
# 2. FASTAPI APPLICATION SETUP
# =====================================================================
app = FastAPI(
    title="Aura Gateway Core API",
    description="Enterprise Multi-Agent LLM Gateway & Execution Engine built with LangGraph, LiteLLM, and Phase 4 Memory Profiling.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register Primary Routers
app.include_router(auth_router)
if github_auth_router:
    app.include_router(github_auth_router)


# =====================================================================
# 3. HELPER UTILITIES & SCHEMAS
# =====================================================================
async def fetch_user_memory_summary(user_id: str) -> Optional[str]:
    """Retrieves long-term user memory profile from DB to inject into graph execution context."""
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalars().first()
            if not user:
                return None
            
            return (
                f"User Name: {user.full_name or 'N/A'}\n"
                f"User Email: {user.email or 'N/A'}"
            )
        except Exception as exc:
            logger.warning(f"⚠️ Could not load memory profile for user '{user_id}': {exc}")
            return None


class ChatRequestPayload(BaseModel):
    user_id: Optional[str] = Field(default="02b7cfb6-f0b2-4d6e-a87b-0b85d4af5fb6", description="Unique ID of the requesting user")
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


class ResumeRequestPayload(BaseModel):
    thread_id: str = Field(..., description="Active session thread ID")
    approved: bool = Field(..., description="Human approval decision")


# =====================================================================
# 4. ASYNCHRONOUS INGESTION WORKER
# =====================================================================
async def process_document_background_task(job_id: str, file_path: Path, filename: str):
    """Processes document parsing and node summary generation asynchronously to prevent HTTP timeouts."""
    from app.nodes.rag import _vectorless_engine_instance

    try:
        logger.info(f"🔄 [ASYNC INGESTION] Starting job '{job_id}' for file: {filename}")
        ingestion_jobs[job_id]["status"] = "processing"
        ingestion_jobs[job_id]["progress"] = 15

        file_hash = _vectorless_engine_instance.compute_file_hash(str(file_path))

        root_tree = _vectorless_engine_instance.load_tree_from_cache(file_hash)
        if not root_tree:
            ingestion_jobs[job_id]["progress"] = 40
            root_tree = await _vectorless_engine_instance.parse_file_to_tree(str(file_path))
            
            ingestion_jobs[job_id]["progress"] = 75
            await _vectorless_engine_instance.generate_node_summaries(root_tree)
            
            _vectorless_engine_instance.save_tree_to_cache(file_hash, root_tree)

        ingestion_jobs[job_id]["status"] = "completed"
        ingestion_jobs[job_id]["progress"] = 100
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
        ingestion_jobs[job_id]["progress"] = 0
        ingestion_jobs[job_id]["error"] = str(exc)


# =====================================================================
# 5. SSE STREAMING GENERATOR
# =====================================================================
async def event_stream_generator(payload: ChatRequestPayload) -> AsyncGenerator[str, None]:
    if not compiled_aura_graph:
        yield f"data: {json.dumps({'type': 'error', 'message': 'Graph engine is uninitialized.'})}\n\n"
        return

    resolved_user_id = payload.user_id if payload.user_id and payload.user_id != "user_default" else "02b7cfb6-f0b2-4d6e-a87b-0b85d4af5fb6"
    logger.info(f"🌊 [STREAM] Initiating event stream for thread '{payload.thread_id}' (User: {resolved_user_id})...")

    memory_profile = await fetch_user_memory_summary(resolved_user_id)

    user_context = UserProfileContext(
        user_id=resolved_user_id,
        department=payload.department,
        role_title=payload.role_title,
        preferred_language=payload.preferred_language,
    )

    initial_state = {
        "messages": [HumanMessage(content=payload.message)],
        "user_id": resolved_user_id,
        "user_context": user_context,
        "staged_action_payload": {
            "resolved_query": payload.message, 
            "raw_text": payload.message,
            "file_hash": payload.file_hash,
            "document_ref": payload.document_ref,
            "user_memory_profile": memory_profile,
        },
    }

    config = {"configurable": {"thread_id": payload.thread_id}}

    try:
        async for event in compiled_aura_graph.astream_events(initial_state, config=config, version="v2"):
            kind = event.get("event")
            node_name = event.get("name", "")

            if kind == "on_chain_start" and node_name in ["pii_redaction", "supervisor_router", "general_agent", "rag_engine", "data_extractor", "email_agent", "github_agent"]:
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

    resolved_user_id = payload.user_id if payload.user_id and payload.user_id != "user_default" else "02b7cfb6-f0b2-4d6e-a87b-0b85d4af5fb6"
    logger.info(f"📩 [REQUEST] Processing query for thread '{payload.thread_id}' from user '{resolved_user_id}'...")

    memory_profile = await fetch_user_memory_summary(resolved_user_id)

    user_context = UserProfileContext(
        user_id=resolved_user_id,
        department=payload.department,
        role_title=payload.role_title,
        preferred_language=payload.preferred_language,
    )

    initial_state = {
        "messages": [HumanMessage(content=payload.message)],
        "user_id": resolved_user_id,
        "user_context": user_context,
        "staged_action_payload": {
            "resolved_query": payload.message, 
            "raw_text": payload.message,
            "file_hash": payload.file_hash,
            "document_ref": payload.document_ref,
            "user_memory_profile": memory_profile,
        },
    }

    config = {"configurable": {"thread_id": payload.thread_id}}

    try:
        final_state = await compiled_aura_graph.ainvoke(initial_state, config=config)

        response_text = "No response generated."
        if final_state.get("messages"):
            response_text = str(final_state["messages"][-1].content)

        active_route = "GENERAL_AGENT"
        router_state = final_state.get("router_state")
        if isinstance(router_state, dict) and "active_route" in router_state:
            active_route = router_state["active_route"]
        elif router_state and hasattr(router_state, "active_route"):
            active_route = router_state.active_route

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


@app.post("/api/v1/chat/resume", tags=["Execution Engine"])
async def resume_interrupted_chat(payload: ResumeRequestPayload):
    """Resumes a paused state graph execution following a Human-In-The-Loop interrupt."""
    if not compiled_aura_graph:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="State graph engine is uninitialized."
        )

    config = {"configurable": {"thread_id": payload.thread_id}}

    try:
        logger.info(f"🔄 [RESUME REQUEST] Resuming workflow for thread '{payload.thread_id}' with decision: approved={payload.approved}")
        
        final_state = await compiled_aura_graph.ainvoke(
            Command(resume={"approved": payload.approved}),
            config=config
        )

        response_text = "Action processed."
        if final_state.get("messages"):
            response_text = str(final_state["messages"][-1].content)

        return {
            "thread_id": payload.thread_id,
            "response": response_text,
            "status": "resumed"
        }
    except Exception as exc:
        logger.error(f"❌ [RESUME ERROR] Failed to resume workflow execution: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to resume execution: {str(exc)}",
        )


@app.post("/api/v1/chat/stream", tags=["Execution Engine"])
async def execute_chat_query_stream(payload: ChatRequestPayload):
    return StreamingResponse(
        event_stream_generator(payload),
        media_type="text/event-stream"
    )


@app.post("/api/v1/documents/upload", status_code=status.HTTP_202_ACCEPTED, tags=["Ingestion Engine"])
async def upload_document_endpoint(
    background_tasks: BackgroundTasks, 
    file: UploadFile = File(...)
):
    """
    Immediate HTTP 202 Response (< 500ms).
    Dispatches document parsing and lazy ingestion to a background worker queue.
    """
    allowed_extensions = {".pdf", ".docx", ".xlsx", ".pptx", ".txt", ".md"}
    file_ext = Path(file.filename).suffix.lower()

    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format '{file_ext}'. Allowed formats: {list(allowed_extensions)}"
        )

    job_id = str(uuid.uuid4())
    saved_file_path = UPLOAD_DIR / f"{job_id}_{file.filename}"

    try:
        with saved_file_path.open("wb") as buffer:
            while chunk := await file.read(1024 * 1024):
                buffer.write(chunk)

        ingestion_jobs[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "progress": 0,
            "filename": file.filename,
            "file_path": str(saved_file_path)
        }

        background_tasks.add_task(
            process_document_background_task, 
            job_id, 
            saved_file_path, 
            file.filename
        )

        return {
            "status": "accepted",
            "job_id": job_id,
            "filename": file.filename,
            "message": "Document upload accepted. Asynchronous ingestion initialized."
        }

    except Exception as exc:
        logger.error(f"❌ [UPLOAD ERROR] Failed to save file '{file.filename}': {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save document: {str(exc)}"
        )


@app.get("/api/v1/documents/status/{job_id}", tags=["Ingestion Engine"])
async def get_ingestion_job_status(job_id: str):
    """Allows frontend UI to poll the background document ingestion status."""
    if job_id not in ingestion_jobs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ingestion job ID not found."
        )
    return ingestion_jobs[job_id]


# =====================================================================
# 7. DIRECT SERVER ENTRYPOINT
# =====================================================================
if __name__ == "__main__":
    server_port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app.main:app", host="0.0.0.0", port=server_port, reload=True)