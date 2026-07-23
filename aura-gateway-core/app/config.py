"""
Aura Gateway Core - Centralized Model & Environment Configuration
"""

import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # API Provider Keys
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")

    # Node Model Registry (Centralized Model Assignment)
    LLM_ROUTER_MODEL: str = "groq/llama-3.1-8b-instant"
    LLM_ROUTER_FALLBACK: str = "openrouter/meta-llama/llama-3.2-3b-instruct:free"

    LLM_RAG_PRIMARY: str = "gemini/gemini-2.5-flash"
    LLM_RAG_FALLBACK: str = "openrouter/nvidia/nemotron-3-ultra:free"

    LLM_GENERAL_PRIMARY: str = "groq/openai/gpt-oss-120b"
    LLM_GENERAL_FALLBACK: str = "groq/llama-3.3-70b-versatile"

    class Config:
        env_file = ".env"
        extra = "ignore"


# Global Config Instance
settings = Settings()