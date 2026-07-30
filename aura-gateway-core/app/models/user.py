import uuid
from sqlalchemy import Column, String, DateTime, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.sql import func
from app.db import Base

class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: f"usr_{uuid.uuid4().hex[:12]}")
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=False)

    # Long-Term Memory & Preference Fields
    role_or_title = Column(String, nullable=False)
    primary_goal = Column(Text, nullable=False)
    preferred_tone = Column(String, default="Direct & Concise")
    
    # Updated: Uses PostgreSQL ARRAY(String) to match character varying[] column type
    domain_expertise = Column(ARRAY(String), default=list)
    additional_context = Column(Text, nullable=True, default="")

    created_at = Column(DateTime(timezone=True), server_default=func.now())