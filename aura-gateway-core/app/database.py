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

# Dynamically resolve .env path relative to database.py location
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
if not ENV_PATH.exists():
    ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"

# Explicitly load environment variables from resolved .env file path
load_dotenv(dotenv_path=ENV_PATH)

# Configure module-level logger
logger = logging.getLogger(__name__)

# Retrieve Neon.tech Postgres connection string strictly from environment
NEON_DATABASE_URL: str | None = os.getenv("DATABASE_URL")

if not NEON_DATABASE_URL:
    raise RuntimeError(
        "❌ [CRITICAL ERROR] DATABASE_URL environment variable is missing!\n"
        f"Attempted loading from: {ENV_PATH}\n"
        "Please ensure you have defined DATABASE_URL in your .env file."
    )

print("🔌 [DATABASE INIT] Configuring serverless PostgreSQL connection pool...")

# Configure asynchronous connection pool without auto-opening on sync import
postgres_connection_pool: AsyncConnectionPool = AsyncConnectionPool(
    conninfo=NEON_DATABASE_URL,
    max_size=20,
    open=False,  # Open pool lazily inside async context
    kwargs={"autocommit": True, "prepare_threshold": 0},
)


@asynccontextmanager
async def get_checkpointer() -> AsyncGenerator[AsyncPostgresSaver, None]:
    """
    Async context manager supplying the LangGraph AsyncPostgresSaver checkpointer.
    Automatically sets up required checkpointer database tables on initial run.

    Yields:
        AsyncPostgresSaver: Active database checkpointer instance.
    """
    print("💾 [DATABASE CHECKPOINTER] Acquiring database connection for superstep checkpointer...")
    try:
        if postgres_connection_pool.closed:
            await postgres_connection_pool.open()
            
        async with postgres_connection_pool.connection() as async_db_connection:
            async_checkpointer: AsyncPostgresSaver = AsyncPostgresSaver(async_db_connection)
            print("⚙️ [DATABASE CHECKPOINTER] Executing checkpointer schema setup...")
            await async_checkpointer.setup()
            print("✅ [DATABASE CHECKPOINTER] Checkpointer ready for superstep serialization.")
            yield async_checkpointer
    except Exception as checkpointer_error:
        print(f"❌ [DATABASE ERROR] Failed to yield checkpointer context: {str(checkpointer_error)}")
        raise checkpointer_error


@asynccontextmanager
async def get_long_term_store() -> AsyncGenerator[AsyncPostgresStore, None]:
    """
    Async context manager supplying the LangGraph AsyncPostgresStore for persistent profiles.

    Yields:
        AsyncPostgresStore: Active long-term memory store instance.
    """
    print("🧠 [DATABASE STORE] Acquiring database connection for long-term profile memory...")
    try:
        if postgres_connection_pool.closed:
            await postgres_connection_pool.open()
            
        async with postgres_connection_pool.connection() as async_db_connection:
            async_long_term_store: AsyncPostgresStore = AsyncPostgresStore(async_db_connection)
            print("⚙️ [DATABASE STORE] Executing store schema setup...")
            await async_long_term_store.setup()
            print("✅ [DATABASE STORE] Long-term memory store ready for profile queries.")
            yield async_long_term_store
    except Exception as store_error:
        print(f"❌ [DATABASE ERROR] Failed to yield long-term store context: {str(store_error)}")
        raise store_error