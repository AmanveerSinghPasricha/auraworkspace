"""
Aura Gateway Core - External Docling Parser API Client
======================================================
Sends PDF files to whatever API endpoint is configured in DOCLING_API_URL.
Handles dynamic ENV evaluation, ngrok headers, and timeout resilience.
"""

import os
import httpx
import logging
from typing import Dict, Any

logger = logging.getLogger("docling_client")


async def parse_pdf_via_api(file_path: str, timeout_seconds: float = 600.0) -> Dict[str, Any]:
    """
    Sends a local PDF file to the external Docling API endpoint.
    Returns the parsed JSON schema or Markdown text.
    """
    # Evaluate URL dynamically on each request to pick up .env updates reliably
    api_url = os.getenv("DOCLING_API_URL", "http://localhost:8001/parse")

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    filename = os.path.basename(file_path)
    logger.info(f"🌐 [DOCLING API] Sending '{filename}' to parser endpoint: {api_url}")

    # Custom headers to bypass ngrok browser interstitial warning pages
    headers = {
        "ngrok-skip-browser-warning": "true",
        "User-Agent": "AuraGatewayClient/1.0"
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds), headers=headers) as client:
        with open(file_path, "rb") as f:
            files = {"file": (filename, f, "application/pdf")}
            
            try:
                response = await client.post(api_url, files=files)
                response.raise_for_status()
                data = response.json()
                
                logger.info(f"✅ [DOCLING API] Successfully received parsed output for '{filename}'")
                return data

            except httpx.HTTPStatusError as exc:
                logger.error(f"❌ [DOCLING API ERROR] Server returned {exc.response.status_code}: {exc.response.text}")
                raise RuntimeError(f"Docling API failed with status {exc.response.status_code}") from exc
            except Exception as exc:
                logger.error(f"❌ [DOCLING API ERROR] Could not connect to {api_url}: {exc}")
                raise RuntimeError(f"Docling API connection error: {str(exc)}") from exc