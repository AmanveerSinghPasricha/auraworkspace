"""
Aura Gateway Core - Exa AI Neural Web Search Service
====================================================
Uses Exa AI's semantic search and extractive highlights for token-efficient real-time retrieval.
"""

import os
import logging
from typing import Dict, Any
from dotenv import load_dotenv
from app.config import settings

logger = logging.getLogger("exa_search")

# Check if exa-py is installed
try:
    from exa_py import AsyncExa
    HAS_EXA_SDK = True
except ImportError:
    HAS_EXA_SDK = False


async def execute_exa_search(query: str, num_results: int = 5) -> Dict[str, Any]:
    """
    Executes a neural web search using Exa AI and retrieves extractive highlights.
    Dynamically fetches environment variables on every call to prevent stale key errors.
    """
    if not HAS_EXA_SDK:
        logger.error("❌ `exa-py` library is not installed. Run `pip install exa-py`.")
        return {
            "query": query,
            "results": [],
            "error": "The `exa-py` package is not installed."
        }

    # Reload environment to ensure dynamic key evaluation
    load_dotenv(override=True)
    exa_key = getattr(settings, "EXA_API_KEY", None) or os.getenv("EXA_API_KEY")

    if not exa_key:
        logger.warning("⚠️ EXA_API_KEY missing from environment. Returning fallback notice.")
        return {
            "query": query,
            "results": [],
            "error": "EXA_API_KEY is not configured in environment settings."
        }

    try:
        # Initialize client per call to stay resilient to env reloads
        exa_client = AsyncExa(api_key=exa_key)
        
        logger.info(f"🌐 [EXA SEARCH] Executing neural search for: '{query}'...")
        
        # Execute search with extractive highlights enabled
        response = await exa_client.search(
            query=query,
            num_results=num_results,
            type="auto",
            contents={"highlights": True}
        )

        formatted_results = []
        for item in getattr(response, "results", []):
            # Safe extraction of highlights list
            raw_highlights = getattr(item, "highlights", []) or []
            highlights_text = "\n".join(raw_highlights) if isinstance(raw_highlights, list) else str(raw_highlights)
            
            formatted_results.append({
                "title": getattr(item, "title", "Untitled") or "Untitled",
                "url": getattr(item, "url", "") or "",
                "published_date": getattr(item, "published_date", "N/A") or "N/A",
                "highlights": highlights_text
            })

        return {
            "query": query,
            "results": formatted_results
        }

    except Exception as exc:
        logger.error(f"❌ [EXA SEARCH ERROR] Failed to perform search: {exc}", exc_info=True)
        return {"query": query, "results": [], "error": str(exc)}