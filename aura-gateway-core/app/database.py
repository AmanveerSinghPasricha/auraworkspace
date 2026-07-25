"""
Aura Gateway Core - Serverless Database Persistence Layer

This module manages connections to Neon.tech serverless PostgreSQL and provides
LangGraph context managers for short-term checkpointers and long-term stores.
"""

import os
import logging
from pathlib import Path
from typing import AsyncGenerator
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres import AsyncPostgresStore

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
if not ENV_PATH.exists():
    ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"

load_dotenv(dotenv_path=ENV_PATH)

logger = logging.getLogger(__name__)

NEON_DATABASE_URL: str | None = os.getenv("DATABASE_URL")

if not NEON_DATABASE_URL:
    raise RuntimeError(
        "? [CRITICAL ERROR] DATABASE_URL environment variable is missing!\n"
        f"Attempted loading from: {ENV_PATH}\n"
        "Please ensure you have defined DATABASE_URL in your .env file."
    )

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
        logger.info("? [DATABASE INIT] Opening serverless PostgreSQL connection pool...")
        await postgres_connection_pool.open()
        logger.info("? [DATABASE INIT] Connection pool opened successfully.")
    return postgres_connection_pool


async def close_db_pool():
    """Safely closes active connection pools on shutdown."""
    if not postgres_connection_pool.closed:
        logger.info("?? [DATABASE CLOSE] Closing PostgreSQL connection pool...")
        await postgres_connection_pool.close()
        logger.info("? [DATABASE CLOSE] Connection pool closed.")


@asynccontextmanager
async def get_checkpointer() -> AsyncGenerator[AsyncPostgresSaver, None]:
    """Yields a thread-safe AsyncPostgresSaver checkpointer context for LangGraph state management."""
    logger.info("?? [DATABASE CHECKPOINTER] Acquiring database connection for checkpointer...")
    try:
        pool = await get_db_pool()
        async with pool.connection() as async_db_connection:
            async_checkpointer = AsyncPostgresSaver(async_db_connection)
            await async_checkpointer.setup()
            yield async_checkpointer
    except Exception as checkpointer_error:
        logger.error(f"? [DATABASE ERROR] Failed to yield checkpointer context: {checkpointer_error}")
        raise checkpointer_error


@asynccontextmanager
async def get_long_term_store() -> AsyncGenerator[AsyncPostgresStore, None]:
    """Yields a thread-safe AsyncPostgresStore context for persistent long-term memory."""
    logger.info("?? [DATABASE STORE] Acquiring database connection for long-term store...")
    try:
        pool = await get_db_pool()
        async with pool.connection() as async_db_connection:
            async_long_term_store = AsyncPostgresStore(async_db_connection)
            await async_long_term_store.setup()
            yield async_long_term_store
    except Exception as store_error:
        logger.error(f"? [DATABASE ERROR] Failed to yield long-term store context: {store_error}")
        raise store_error
