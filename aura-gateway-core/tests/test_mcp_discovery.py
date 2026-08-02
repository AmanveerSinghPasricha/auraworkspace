import asyncio
import logging
from app.services.mcp_service import mcp_registry

logging.basicConfig(level=logging.INFO)

async def test_mcp():
    print("🔍 Discovering and loading LiteLLM tools from aura-mcp-tools...")
    tools = await mcp_registry.get_litellm_tools()
    print(f"\n✅ Total Discovered Tools: {len(tools)}")
    for t in tools:
        print(f"  • Tool Name: {t['function']['name']}")
        print(f"    Description: {t['function']['description']}\n")

if __name__ == "__main__":
    asyncio.run(test_mcp())