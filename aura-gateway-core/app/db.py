import os
import ssl
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base

# Load environment variables
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=BASE_DIR / ".env")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/auradb"
)

# Detect if SSL was requested originally in the query parameters
raw_url_lower = DATABASE_URL.lower()
requires_ssl = "neon.tech" in raw_url_lower or "ssl" in raw_url_lower or "sslmode" in raw_url_lower

# 1. Convert driver scheme to asyncpg if standard postgresql://
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

# 2. Strip parameters (ssl, sslmode, channel_binding) that break asyncpg & pool connections
parsed_url = urlparse(DATABASE_URL)
if parsed_url.query:
    query_params = parse_qs(parsed_url.query)
    query_params.pop("sslmode", None)
    query_params.pop("ssl", None)
    query_params.pop("channel_binding", None)
    
    new_query = urlencode(query_params, doseq=True)
    DATABASE_URL = urlunparse((
        parsed_url.scheme,
        parsed_url.netloc,
        parsed_url.path,
        parsed_url.params,
        new_query,
        parsed_url.fragment
    ))

# 3. Base engine configuration
engine_kwargs = {
    "echo": False,
    "future": True,
}

# 4. Configure dialect-specific engine parameters
if "sqlite" not in DATABASE_URL:
    connect_args = {}
    if requires_ssl:
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        connect_args["ssl"] = ssl_context

    # Pooling arguments applied only for PostgreSQL
    engine_kwargs.update({
        "pool_pre_ping": True,
        "pool_recycle": 300,
        "pool_size": 10,
        "max_overflow": 20,
        "connect_args": connect_args,
    })

engine = create_async_engine(DATABASE_URL, **engine_kwargs)

# Configured cleanly for SQLAlchemy 2.0 Async Session Factory
AsyncSessionLocal = async_sessionmaker(
    engine, 
    class_=AsyncSession, 
    expire_on_commit=False
)

Base = declarative_base()

async def get_db():
    """FastAPI dependency yielding an async database session per request."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise