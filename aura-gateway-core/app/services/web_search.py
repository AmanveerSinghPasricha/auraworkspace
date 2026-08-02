"""
Aura Gateway Core - Real-Time Web Search Service (Tavily Fallback)
===================================================================
Provides real-time web search capabilities using Tavily API.
"""

import os
import logging
from typing import Dict, Any
from app.config import settings

logger = logging.getLogger("web_search")

# Check if tavily-python package is available
try:
    from tavily import AsyncTavilyClient
    tavily_key = getattr(settings, "TAVILY_API_KEY", os.getenv("TAVILY_API_KEY"))
    tavily_client = AsyncTavilyClient(api_key=tavily_key) if tavily_key else None
except ImportError:
    tavily_client = None


async def execute_web_search(query: str, max_results: int = 5) -> Dict[str, Any]:
    """
    Executes a real-time web search for fresh intelligence.
    """
    if not tavily_client:
        logger.warning("⚠️ Tavily client not configured or missing API key. Returning fallback notice.")
        return {
            "query": query,
            "answer": "Tavily search is unconfigured.",
            "results": [],
            "error": "TAVILY_API_KEY missing or tavily-python not installed."
        }

    try:
        logger.info(f"🌐 [TAVILY SEARCH] Querying web for: '{query}'...")
        response = await tavily_client.search(
            query=query,
            search_depth="advanced",
            max_results=max_results,
            include_answer=True,
        )

        formatted_results = []
        for result in response.get("results", []):
            formatted_results.append({
                "title": result.get("title"),
                "url": result.get("url"),
                "snippet": result.get("content"),
                "published_date": result.get("published_date", "N/A")
            })

        return {
            "query": query,
            "answer": response.get("answer", ""),
            "results": formatted_results
        }

    except Exception as exc:
        logger.error(f"❌ [WEB SEARCH ERROR] Failed to perform web search: {exc}")
        return {"query": query, "results": [], "error": str(exc)}