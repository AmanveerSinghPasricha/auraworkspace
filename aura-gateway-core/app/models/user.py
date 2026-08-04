"""
User Database Model (Neon Postgres / SQLAlchemy 2.0)
=====================================================
Extends the user model to support multi-tenant GitHub & Smithery connection mapping.
"""

from typing import Optional
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Password field for Auth
    password_hash: Mapped[str] = mapped_column(String, nullable=False)

    # Smithery AI Managed Connection ID
    smithery_connection_id: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True,
        default=None,
        index=True,
        doc="Stores the Smithery connection ID issued after user consents via OAuth flow"
    )

    # Encrypted GitHub OAuth Access Token
    github_access_token: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        default=None,
        doc="Encrypted GitHub access token for multi-tenant MCP tool invocation"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )