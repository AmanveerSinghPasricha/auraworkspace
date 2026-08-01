"""
Aura Gateway Core - Serverless Database Persistence Layer

This module manages connections to Neon.tech serverless PostgreSQL and provides
LangGraph context managers for short-term checkpointers and long-term stores.
Includes Windows SelectorEventLoop enforcement for Psycopg3 compatibility.
"""

import sys
import os
import asyncio
import logging
from pathlib import Path
from typing import AsyncGenerator
from contextlib import asynccontextmanager
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from dotenv import load_dotenv
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres import AsyncPostgresStore

# ---------------------------------------------------------------------
# 0. WINDOWS ASYNC EVENT LOOP POLICY ENFORCEMENT FOR PSYCOPG3
# ---------------------------------------------------------------------
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
if not ENV_PATH.exists():
    ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"

load_dotenv(dotenv_path=ENV_PATH)

logger = logging.getLogger(__name__)

RAW_DATABASE_URL: str | None = os.getenv("DATABASE_URL")

if not RAW_DATABASE_URL:
    raise RuntimeError(
        "❌ [CRITICAL ERROR] DATABASE_URL environment variable is missing!\n"
        f"Attempted loading from: {ENV_PATH}\n"
        "Please ensure you have defined DATABASE_URL in your .env file."
    )


def clean_url_for_psycopg(url: str) -> str:
    """Sanitizes SQLAlchemy asyncpg URLs so psycopg-pool accepts them."""
    # Convert driver scheme back to standard postgresql://
    if url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql://", 1)

    parsed = urlparse(url)
    if parsed.query:
        query_params = parse_qs(parsed.query)
        # Remove parameters incompatible with psycopg driver
        query_params.pop("channel_binding", None)

        new_query = urlencode(query_params, doseq=True)
        url = urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            parsed.fragment
        ))
    return url


NEON_DATABASE_URL = clean_url_for_psycopg(RAW_DATABASE_URL)

# Async Connection Pool optimized for Neon Serverless PgBouncer
postgres_connection_pool: AsyncConnectionPool = AsyncConnectionPool(
    conninfo=NEON_DATABASE_URL,
    min_size=1,
    max_size=20,
    max_idle=300,             # Drop connections idle for >5 mins to align with Neon suspend
    max_lifetime=1800,        # Periodically recycle connections every 30 minutes
    reconnect_timeout=10,     # Time to wait during cold-start reconnections
    open=False,
    kwargs={
        "autocommit": True,
        "prepare_threshold": 0,  # Required for PgBouncer / Neon transaction pooling
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 5,
    },
)


async def get_db_pool() -> AsyncConnectionPool:
    """Returns an active PostgreSQL async connection pool instance."""
    if postgres_connection_pool.closed:
        logger.info("ℹ️ [DATABASE INIT] Opening serverless PostgreSQL connection pool...")
        await postgres_connection_pool.open()
        logger.info("✅ [DATABASE INIT] Connection pool opened successfully.")
    return postgres_connection_pool


async def close_db_pool():
    """Safely closes active connection pools on shutdown."""
    if not postgres_connection_pool.closed:
        logger.info("ℹ️ [DATABASE CLOSE] Closing PostgreSQL connection pool...")
        await postgres_connection_pool.close()
        logger.info("✅ [DATABASE CLOSE] Connection pool closed.")


@asynccontextmanager
async def get_checkpointer() -> AsyncGenerator[AsyncPostgresSaver, None]:
    """Yields a thread-safe AsyncPostgresSaver checkpointer context for LangGraph state management."""
    logger.info("ℹ️ [DATABASE CHECKPOINTER] Acquiring database connection for checkpointer...")
    try:
        pool = await get_db_pool()
        async with pool.connection() as async_db_connection:
            async_checkpointer = AsyncPostgresSaver(async_db_connection)
            await async_checkpointer.setup()
            yield async_checkpointer
    except Exception as checkpointer_error:
        logger.error(f"❌ [DATABASE ERROR] Failed to yield checkpointer context: {checkpointer_error}")
        raise checkpointer_error


@asynccontextmanager
async def get_long_term_store() -> AsyncGenerator[AsyncPostgresStore, None]:
    """Yields a thread-safe AsyncPostgresStore context for persistent long-term memory."""
    logger.info("ℹ️ [DATABASE STORE] Acquiring database connection for long-term store...")
    try:
        pool = await get_db_pool()
        async with pool.connection() as async_db_connection:
            async_long_term_store = AsyncPostgresStore(async_db_connection)
            await async_long_term_store.setup()
            yield async_long_term_store
    except Exception as store_error:
        logger.error(f"❌ [DATABASE ERROR] Failed to yield long-term store context: {store_error}")
        raise store_error