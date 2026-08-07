"""
Smithery AI Service Integration
===============================
Executes tool requests via Smithery AI managed endpoints using per-user connection IDs.
"""

import logging
from typing import Dict, Any
import httpx

from app.config import settings

logger = logging.getLogger("smithery_service")


async def execute_gmail_tool_for_user(
    connection_id: str, 
    tool_name: str, 
    payload: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Executes a Gmail MCP tool via Smithery AI's Managed Connection proxy.
    """
    if not connection_id:
        raise ValueError("Smithery connection ID is required to execute user Gmail tools.")

    url = f"https://smithery.ai/api/v1/tools/gmail/{tool_name}"
    
    headers = {
        "Authorization": f"Bearer {settings.SMITHERY_API_KEY}",
        "X-Smithery-Connection-ID": connection_id,
        "Content-Type": "application/json",
    }

    logger.info(f"📤 [SMITHERY DISPATCH] Executing '{tool_name}' for connection: {connection_id}")

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            result = response.json()
            logger.info(f"✅ [SMITHERY SUCCESS] Tool '{tool_name}' executed successfully.")
            return {"status": "success", "data": result}

        except httpx.HTTPStatusError as exc:
            error_msg = f"Smithery API HTTP Error {exc.response.status_code}: {exc.response.text}"
            logger.error(f"❌ [SMITHERY HTTP ERROR] {error_msg}")
            return {"status": "error", "message": error_msg}

        except Exception as exc:
            error_msg = f"Failed to dispatch request to Smithery AI: {str(exc)}"
            logger.error(f"❌ [SMITHERY EXCEPTION] {error_msg}")
            return {"status": "error", "message": error_msg}