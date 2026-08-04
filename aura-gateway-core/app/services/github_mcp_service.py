import json
import logging
from typing import Dict, Any
from langchain_mcp_adapters.client import MultiServerMCPClient

from app.core.security import decrypt_token

logger = logging.getLogger("github_mcp_service")


async def execute_github_mcp_tool_for_user(
    encrypted_token: str,
    tool_name: str,
    arguments: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Dynamically initializes the GitHub MCP Server with the individual user's decrypted token.
    Compatible with langchain-mcp-adapters >= 0.1.0 session context model.
    """
    raw_token = decrypt_token(encrypted_token)
    if not raw_token:
        return {"status": "error", "message": "User GitHub access token is invalid or missing."}

    # Dynamic MCP STDIO Server configuration injecting user token
    server_config = {
        "github": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-github"],
            "env": {
                "GITHUB_PERSONAL_ACCESS_TOKEN": raw_token
            },
            "transport": "stdio"
        }
    }

    try:
        logger.info(f"⚡ [MCP RUNNER] Initializing GitHub MCP client for tool: '{tool_name}'")
        client = MultiServerMCPClient(server_config)

        # Open session specifically for the "github" server
        async with client.session("github") as session:
            logger.info(f"🔌 [MCP SESSION] Invoking tool '{tool_name}' over STDIO session...")
            result = await session.call_tool(
                name=tool_name,
                arguments=arguments
            )

            logger.info(f"✅ [MCP RUNNER SUCCESS] Tool '{tool_name}' executed successfully.")
            
            # Format output content safely
            content_output = getattr(result, "content", result)
            
            return {
                "status": "success",
                "result": content_output,
                "data": content_output
            }

    except Exception as exc:
        logger.error(f"❌ [MCP RUNNER EXCEPTION] Call failed for tool '{tool_name}': {str(exc)}", exc_info=True)
        return {"status": "error", "message": str(exc)}