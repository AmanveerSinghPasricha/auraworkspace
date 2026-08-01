"""
Aura Gateway Core - Centralized Model & Environment Configuration
"""

import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # App Settings
    APP_NAME: str = "Aura Gateway Core"

    # API Provider Keys
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")

    # Node Model Registry
    LLM_ROUTER_MODEL: str = "groq/llama-3.3-70b-versatile"
    LLM_ROUTER_FALLBACK: str = "groq/llama-3.1-8b-instant"

    # Core RAG Stack: Primary = Groq Llama 3.3 70B | Fallback = Groq Llama 3.1 8B
    LLM_RAG_PRIMARY: str = "groq/llama-3.3-70b-versatile"
    LLM_RAG_FALLBACK: str = "groq/llama-3.1-8b-instant"

    LLM_EXTRACTOR_PRIMARY: str = "groq/llama-3.3-70b-versatile"
    LLM_EXTRACTOR_FALLBACK: str = "groq/llama-3.1-8b-instant"

    LLM_GENERAL_PRIMARY: str = "groq/llama-3.3-70b-versatile"
    LLM_GENERAL_FALLBACK: str = "groq/llama-3.1-8b-instant"

    class Config:
        env_file = ".env"
        extra = "ignore"


# Global Config Instance
settings = Settings()