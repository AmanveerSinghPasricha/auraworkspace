"""
Aura Gateway Core - Enterprise Multi-Agent Execution Engine
===========================================================
Production API Gateway managing multi-agent graph workflows, thread-scoped state 
checkpoints, Human-In-The-Loop (HITL) approval interrupts, and asynchronous 
document ingestion pipelines.
"""

import os
import json
import uuid
import logging
import uvicorn
import threading
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Dict, Any, List, Optional, AsyncGenerator

from fastapi import FastAPI, HTTPException, Depends, Header, status, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage
from langgraph.types import Command
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy.future import select

from app.config import settings
from app.database import get_db_pool, close_db_pool
from app.db import engine, Base, AsyncSessionLocal
from app.models.user import User

# Auth Routers
from app.routers.auth import router as auth_router
try:
    from app.routers.github_auth import router as github_auth_router
except ImportError:
    github_auth_router = None

from app.state import UserProfileContext

# OS Optimizations for High-Concurrency Execution & Reduced RAM Footprint
os.environ["MALLOC_TRIM_THRESHOLD_"] = "65536"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"

logger = logging.getLogger("aura_main")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

UPLOAD_DIR = Path("./uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Global Graph & Checkpointer Singletons
compiled_aura_graph = None
checkpointer_instance = MemorySaver()  # Production fallback checkpointer
graph_lock = threading.Lock()
ingestion_jobs: Dict[str, Dict[str, Any]] = {}


def get_compiled_graph():
    """
    Lazy-loads and compiles the LangGraph multi-agent state machine on first execution.
    Prevents heavy ML module loads on app startup to avoid Render Exit 137 OOM crashes.
    """
    global compiled_aura_graph, checkpointer_instance
    if compiled_aura_graph is None:
        with graph_lock:
            if compiled_aura_graph is None:
                logger.info("⚙️ [GRAPH ENGINE] Compiling LangGraph state machine (Lazy Loaded)...")
                from app.graph import create_aura_graph
                compiled_aura_graph = create_aura_graph(checkpointer=checkpointer_instance, store=None)
                logger.info("✅ [GRAPH ENGINE] State machine compiled successfully.")
    return compiled_aura_graph


# =====================================================================
# 1. LIFECYCLE MANAGEMENT (STARTUP / SHUTDOWN)
# =====================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manages database pool initialization and ORM schema creation on startup.
    Graph compilation is deferred to first request access for fast, low-RAM boot.
    """
    logger.info("🚀 [GATEWAY STARTUP] Bootstrapping Aura Gateway Core Service...")

    try:
        pool = await get_db_pool()
        logger.info("✅ [DATABASE Pool] Connection pool initialized successfully.")

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("✅ [DATABASE ORM] Schema verified & active.")

    except Exception as exc:
        logger.error(f"❌ [STARTUP WARNING] Database initialization issue: {exc}", exc_info=True)

    yield

    logger.info("🛑 [GATEWAY SHUTDOWN] Safely terminating database connection pool...")
    await close_db_pool()


# =====================================================================
# 2. APPLICATION SETUP & MIDDLEWARE
# =====================================================================
app = FastAPI(
    title="Aura Gateway Core API",
    description="Production Multi-Agent LLM Orchestrator built with LangGraph and FastAPI.",
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

app.include_router(auth_router)
if github_auth_router:
    app.include_router(github_auth_router)


# =====================================================================
# 3. DOMAIN SCHEMAS & UTILITIES
# =====================================================================
async def fetch_user_memory_summary(user_id: str) -> Optional[str]:
    """Fetches user profile summary from DB to hydrate multi-agent memory."""
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalars().first()
            if not user:
                return None
            return f"User Name: {user.full_name or 'N/A'}\nUser Email: {user.email or 'N/A'}"
        except Exception as exc:
            logger.warning(f"⚠️ Unable to query user memory context for '{user_id}': {exc}")
            return None


class ChatRequestPayload(BaseModel):
    user_id: Optional[str] = Field(default="02b7cfb6-f0b2-4d6e-a87b-0b85d4af5fb6", description="Authenticated user UUID")
    thread_id: str = Field(default="thread_demo_001", description="Session thread identifier")
    message: str = Field(..., description="User prompt string")
    department: Optional[str] = Field(default="Engineering", description="User department context")
    role_title: Optional[str] = Field(default="Machine Learning Engineer", description="User role title")
    preferred_language: Optional[str] = Field(default="English", description="Target response language")
    file_hash: Optional[str] = Field(default=None, description="Active RAG file hash")
    document_ref: Optional[str] = Field(default=None, description="Active RAG file path reference")


class ChatResponsePayload(BaseModel):
    thread_id: str
    active_route: str
    response: str
    status: str = Field(default="completed", description="Execution status: 'completed' | 'interrupted'")
    interrupt: Optional[Dict[str, Any]] = Field(default=None, description="Staged HITL payload when interrupted")
    pii_redacted: bool = False
    validation_errors: List[str] = Field(default_factory=list)


class ResumeRequestPayload(BaseModel):
    thread_id: str = Field(..., description="Active session thread ID")
    approved: Optional[bool] = Field(default=None, description="Top-level approval decision flag")
    resume_payload: Optional[Dict[str, Any]] = Field(default=None, description="Nested payload from frontend HITL modal")


# =====================================================================
# 4. ASYNCHRONOUS INGESTION WORKER
# =====================================================================
async def process_document_background_task(job_id: str, file_path: Path, filename: str):
    """Parses and indexes uploaded documents asynchronously."""
    from app.nodes.rag import get_vectorless_engine
    vectorless_engine = get_vectorless_engine()

    try:
        logger.info(f"🔄 [ASYNC INGESTION] Starting job '{job_id}' for file: {filename}")
        ingestion_jobs[job_id]["status"] = "processing"
        ingestion_jobs[job_id]["progress"] = 15

        file_hash = vectorless_engine.compute_file_hash(str(file_path))
        root_tree = vectorless_engine.load_tree_from_cache(file_hash)

        if not root_tree:
            ingestion_jobs[job_id]["progress"] = 40
            root_tree = await vectorless_engine.parse_file_to_tree(str(file_path))

            ingestion_jobs[job_id]["progress"] = 75
            await vectorless_engine.generate_node_summaries(root_tree)
            vectorless_engine.save_tree_to_cache(file_hash, root_tree)

        ingestion_jobs[job_id]["status"] = "completed"
        ingestion_jobs[job_id]["progress"] = 100
        ingestion_jobs[job_id]["result"] = {
            "filename": filename,
            "file_path": str(file_path),
            "file_hash": file_hash,
            "chapters_detected": len(root_tree.children) if root_tree else 0,
            "document_ref": str(file_path)
        }
        logger.info(f"✅ [ASYNC INGESTION] Document '{filename}' indexed successfully.")

    except Exception as exc:
        logger.error(f"❌ [ASYNC INGESTION ERROR] Job '{job_id}' failed: {exc}", exc_info=True)
        ingestion_jobs[job_id]["status"] = "failed"
        ingestion_jobs[job_id]["progress"] = 0
        ingestion_jobs[job_id]["error"] = str(exc)


# =====================================================================
# 5. SSE STREAMING GENERATOR
# =====================================================================
async def event_stream_generator(payload: ChatRequestPayload) -> AsyncGenerator[str, None]:
    graph = get_compiled_graph()
    if not graph:
        yield f"data: {json.dumps({'type': 'error', 'message': 'Graph engine is uninitialized.'})}\n\n"
        return

    resolved_user_id = payload.user_id or "02b7cfb6-f0b2-4d6e-a87b-0b85d4af5fb6"
    logger.info(f"🌊 [STREAM] Initializing event stream for thread '{payload.thread_id}' (User: {resolved_user_id})...")

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
        async for event in graph.astream_events(initial_state, config=config, version="v2"):
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
        logger.error(f"❌ [STREAM ERROR] Execution streaming failed: {exc}", exc_info=True)
        yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"


# =====================================================================
# 6. PRIMARY REST ENDPOINTS
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
        logger.error(f"❌ [HEALTH CHECK] DB ping failed: {exc}")

    graph = get_compiled_graph()
    is_healthy = (graph is not None) and db_healthy

    return {
        "status": "healthy" if is_healthy else "unhealthy",
        "service": getattr(settings, "APP_NAME", "Aura Gateway Core"),
        "version": app.version,
        "diagnostics": {
            "graph_compiled": graph is not None,
            "database_connected": db_healthy,
        }
    }


@app.post("/api/v1/chat", response_model=ChatResponsePayload, tags=["Execution Engine"])
async def execute_chat_query(payload: ChatRequestPayload, x_user_id: Optional[str] = Header(None)):
    graph = get_compiled_graph()
    if not graph:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="State graph engine is uninitialized.",
        )

    resolved_user_id = x_user_id or payload.user_id or "02b7cfb6-f0b2-4d6e-a87b-0b85d4af5fb6"
    logger.info(f"📩 [CHAT EXECUTION] Processing thread '{payload.thread_id}' for user '{resolved_user_id}'...")

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
        final_state = await graph.ainvoke(initial_state, config=config)

        # 1. INSPECT STATE FOR INTERRUPTS (HITL PAUSE)
        graph_snapshot = await graph.aget_state(config)

        if graph_snapshot.next:
            interrupt_val = {}
            if graph_snapshot.tasks and graph_snapshot.tasks[0].interrupts:
                interrupt_val = graph_snapshot.tasks[0].interrupts[0].value

            staged_payload = final_state.get("staged_action_payload") or {}

            interrupt_data = interrupt_val or {
                "action_type": staged_payload.get("action_type") or "send_email",
                "recipient": staged_payload.get("recipient") or "pasrichaamanveer@gmail.com",
                "subject": staged_payload.get("subject") or "Verification Test",
                "body": staged_payload.get("body") or payload.message,
            }

            logger.info(f"⏸️ [HITL INTERRUPT TRIGGERED] Thread '{payload.thread_id}' awaiting human confirmation.")

            return ChatResponsePayload(
                thread_id=payload.thread_id,
                active_route="EMAIL_AGENT",
                response="⚠️ Action approval required. Please review the pending action in the approval prompt.",
                status="interrupted",
                interrupt=interrupt_data,
                pii_redacted=False,
                validation_errors=[],
            )

        # 2. STANDARD NON-INTERRUPTED RESPONSE
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
            status="completed",
            pii_redacted=pii_was_redacted,
            validation_errors=final_state.get("validation_errors", []),
        )

    except Exception as exc:
        logger.error(f"❌ [CHAT ROUTE ERROR] Failed executing graph query: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Execution engine failure: {str(exc)}",
        )


@app.post("/api/v1/chat/resume", tags=["Execution Engine"])
async def resume_interrupted_chat(payload: ResumeRequestPayload):
    graph = get_compiled_graph()
    if not graph:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="State graph engine is uninitialized."
        )

    is_approved = payload.approved
    if is_approved is None and payload.resume_payload:
        is_approved = payload.resume_payload.get("approved", True)

    if is_approved is None:
        is_approved = True

    config = {"configurable": {"thread_id": payload.thread_id}}

    try:
        logger.info(f"🔄 [GRAPH RESUME] Resuming thread '{payload.thread_id}' with decision: approved={is_approved}")

        final_state = await graph.ainvoke(
            Command(resume={"approved": is_approved}),
            config=config
        )

        response_text = "Action processed successfully."
        if final_state.get("messages"):
            response_text = str(final_state["messages"][-1].content)

        return {
            "thread_id": payload.thread_id,
            "response": response_text,
            "status": "resumed"
        }
    except Exception as exc:
        logger.error(f"❌ [RESUME ERROR] Failed to resume graph state: {exc}", exc_info=True)
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
    allowed_extensions = {".pdf", ".docx", ".xlsx", ".pptx", ".txt", ".md"}
    file_ext = Path(file.filename).suffix.lower()

    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported format '{file_ext}'. Allowed formats: {list(allowed_extensions)}"
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
        logger.error(f"❌ [UPLOAD ERROR] Failed saving document: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save document: {str(exc)}"
        )


@app.get("/api/v1/documents/status/{job_id}", tags=["Ingestion Engine"])
async def get_ingestion_job_status(job_id: str):
    if job_id not in ingestion_jobs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ingestion job ID not found."
        )
    return ingestion_jobs[job_id]


if __name__ == "__main__":
    server_port = int(os.environ.get("PORT", 10000))
    uvicorn.run("app.main:app", host="0.0.0.0", port=server_port, reload=False)