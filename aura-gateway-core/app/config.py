"""
Aura Gateway Core - Centralized Model & Environment Configuration
"""

import os
from typing import Optional
from pydantic import ConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # App Settings
    APP_NAME: str = "Aura Gateway Core"

    # API Provider Keys
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
    
    # Real-Time Web Intelligence Tools Keys
    EXA_API_KEY: Optional[str] = os.getenv("EXA_API_KEY", None)
    TAVILY_API_KEY: Optional[str] = os.getenv("TAVILY_API_KEY", None)

    # Node Model Registry - Router
    LLM_ROUTER_MODEL: str = "groq/llama-3.3-70b-versatile"
    LLM_ROUTER_FALLBACK: str = "groq/llama-3.1-8b-instant"

    # Core RAG Stack
    LLM_RAG_PRIMARY: str = "groq/llama-3.3-70b-versatile"
    LLM_RAG_FALLBACK: str = "groq/llama-3.1-8b-instant"

    # Extractor Node Stack
    LLM_EXTRACTOR_PRIMARY: str = "groq/llama-3.3-70b-versatile"
    LLM_EXTRACTOR_FALLBACK: str = "groq/llama-3.1-8b-instant"

    # General Agent Stack (Provides aliases for standard LLM naming)
    LLM_GENERAL_PRIMARY: str = "groq/llama-3.3-70b-versatile"
    LLM_GENERAL_FALLBACK: str = "groq/llama-3.1-8b-instant"
    
    @property
    def LLM_PRIMARY(self) -> str:
        return self.LLM_GENERAL_PRIMARY

    @property
    def LLM_FALLBACK(self) -> str:
        return self.LLM_GENERAL_FALLBACK

    model_config = ConfigDict(env_file=".env", extra="ignore")


# Global Config Instance
settings = Settings()