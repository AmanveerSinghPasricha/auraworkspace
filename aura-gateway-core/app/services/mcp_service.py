"""
Aura Gateway Core - Zero-Hardcode AST-Driven MCP Registry Service
==================================================================
"""

import ast
import json
import sys
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from langchain_mcp_adapters.client import MultiServerMCPClient

from app.config import settings

logger = logging.getLogger("mcp_service")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def resolve_mcp_tools_dir() -> Path:
    """Resolves the absolute path to `aura-mcp-tools`."""
    env_mcp_dir = getattr(settings, "MCP_TOOLS_DIR", None)
    if env_mcp_dir and Path(env_mcp_dir).exists():
        return Path(env_mcp_dir).resolve()

    env_workspace_dir = getattr(settings, "AURAWORKSPACE_DIR", None)
    if env_workspace_dir:
        candidate = Path(env_workspace_dir) / "aura-mcp-tools"
        if candidate.exists():
            return candidate.resolve()

    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if parent.name == "auraworkspace" and (parent / "aura-mcp-tools").exists():
            return (parent / "aura-mcp-tools").resolve()
        sibling_mcp = parent / "aura-mcp-tools"
        if sibling_mcp.exists() and sibling_mcp.is_dir():
            return sibling_mcp.resolve()

    return (current.parents[2] / "aura-mcp-tools").resolve()


def inspect_python_file_for_mcp(file_path: Path) -> bool:
    """Parses Python AST to check if the file instantiates FastMCP or runs an MCP server."""
    try:
        content = file_path.read_text(encoding="utf-8")
        if "FastMCP" not in content and "mcp" not in content:
            return False

        tree = ast.parse(content, filename=str(file_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id in ["FastMCP", "Server"]:
                    return True
                elif isinstance(func, ast.Attribute) and func.attr in ["FastMCP", "Server"]:
                    return True
            elif isinstance(node, ast.Attribute) and node.attr == "run":
                return True
    except Exception:
        pass
    return False


def find_mcp_entrypoint(server_dir: Path) -> Optional[Path]:
    """Dynamically finds the MCP server entrypoint using config or AST inspection."""
    mcp_config = server_dir / "mcp.json"
    if mcp_config.exists():
        try:
            cfg = json.loads(mcp_config.read_text(encoding="utf-8"))
            if "entrypoint" in cfg:
                return (server_dir / cfg["entrypoint"]).resolve()
        except Exception:
            pass

    for py_file in server_dir.glob("*.py"):
        if py_file.name.startswith((".", "_")):
            continue
        if inspect_python_file_for_mcp(py_file):
            return py_file.resolve()

    return None


def discover_all_mcp_servers() -> Dict[str, Dict[str, Any]]:
    """Scans `aura-mcp-tools/` and auto-registers servers via AST/Config discovery."""
    mcp_base_dir = resolve_mcp_tools_dir()
    discovered_connections: Dict[str, Dict[str, Any]] = {}
    python_exec = sys.executable

    if not mcp_base_dir.exists() or not mcp_base_dir.is_dir():
        logger.warning(f"⚠️ [MCP DISCOVERY] Base directory missing: {mcp_base_dir}")
        return discovered_connections

    logger.info(f"🔍 [MCP DISCOVERY] AST-scanning directory: {mcp_base_dir}")

    for item in mcp_base_dir.iterdir():
        if item.is_dir() and not item.name.startswith((".", "_")):
            server_name = item.name
            entrypoint = find_mcp_entrypoint(item)

            if entrypoint:
                connection_key = f"{server_name.replace('_server', '')}_mcp" if server_name.endswith("_server") else f"{server_name}_mcp"

                discovered_connections[connection_key] = {
                    "transport": "stdio",
                    "command": python_exec,
                    "args": [str(entrypoint)],
                }
                logger.info(f"✅ [MCP DISCOVERED] '{server_name}' -> AST Entrypoint: {entrypoint.name}")
            else:
                logger.warning(f"⚠️ [MCP DISCOVERY] Ignored folder '{server_name}' (No MCP server code detected)")

    return discovered_connections


class AuraMCPRegistry:
    def __init__(self, connections: Optional[Dict[str, Any]] = None):
        self._custom_connections = connections
        self._mcp_client: Optional[MultiServerMCPClient] = None
        self._tool_map: Dict[str, Any] = {}

    async def initialize(self) -> None:
        if self._mcp_client is None:
            try:
                connections = self._custom_connections or discover_all_mcp_servers()
                if not connections:
                    logger.warning("⚠️ [MCP REGISTRY] No active MCP servers discovered.")
                    return

                logger.info(f"🔌 [MCP REGISTRY] Connection pool starting for: {list(connections.keys())}")
                self._mcp_client = MultiServerMCPClient(
                    connections=connections,
                    tool_name_prefix=True,
                    handle_tool_errors=True,
                )
                logger.info("🔌 [MCP REGISTRY] Connection pool successfully initialized.")
            except Exception as exc:
                logger.error(f"❌ [MCP REGISTRY] Initialization error: {exc}", exc_info=True)

    async def get_litellm_tools(self) -> List[Dict[str, Any]]:
        await self.initialize()
        if not self._mcp_client:
            return []

        try:
            langchain_tools = await self._mcp_client.get_tools()
            self._tool_map = {tool.name: tool for tool in langchain_tools}

            litellm_tools = []
            for tool in langchain_tools:
                schema_args = {}
                if hasattr(tool, "args_schema") and tool.args_schema:
                    if hasattr(tool.args_schema, "schema"):
                        schema_args = tool.args_schema.schema()
                    elif isinstance(tool.args_schema, dict):
                        schema_args = tool.args_schema

                litellm_tools.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description or "External MCP Tool",
                        "parameters": schema_args if schema_args else {"type": "object", "properties": {}}
                    }
                })

            logger.info(f"⚡ [MCP REGISTRY] Registered {len(litellm_tools)} active MCP tools dynamically.")
            return litellm_tools
        except Exception as exc:
            logger.error(f"❌ [MCP REGISTRY] Error fetching tools: {exc}", exc_info=True)
            return []

    async def execute_mcp_tool(self, tool_name: str, tool_args: Dict[str, Any]) -> str:
        await self.initialize()
        if tool_name not in self._tool_map:
            err_msg = f"Tool '{tool_name}' is not registered."
            logger.error(f"❌ [MCP EXECUTION ERROR] {err_msg}")
            return f"Error: {err_msg}"

        try:
            logger.info(f"⚙️ [MCP EXECUTE] Dispatching to '{tool_name}' with args: {tool_args}")
            target_tool = self._tool_map[tool_name]
            result = await target_tool.ainvoke(tool_args)
            return str(result)
        except Exception as exc:
            logger.error(f"❌ [MCP FAILED] Execution error in '{tool_name}': {exc}", exc_info=True)
            return f"Error executing MCP tool '{tool_name}': {str(exc)}"


# MUST BE AT THE BOTTOM: Global Singleton Instance
mcp_registry = AuraMCPRegistry()