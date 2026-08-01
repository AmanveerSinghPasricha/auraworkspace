import sys
import asyncio
from pathlib import Path

# Ensure root directory is on Python path
sys.path.append(str(Path(__file__).parent.parent))

from app.database import get_db_pool, close_db_pool
from app.graph import create_aura_graph


async def run_diagnostics():
    print("\n" + "=" * 60)
    print("?? [AURA DIAGNOSTICS] STARTING GATEWAY CORE HEALTH TEST")
    print("=" * 60 + "\n")

    # 1. Test Database Connection
    print("1?? Testing Database Pool Connection...")
    try:
        pool = await get_db_pool()
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1;")
                print("   ? [DATABASE] Connection successful!")
        await close_db_pool()
    except Exception as exc:
        print(f"   ? [DATABASE ERROR] Connection failed: {exc}")

    # 2. Test LangGraph Compilation
    print("\n2?? Testing LangGraph Compilation...")
    try:
        graph = create_aura_graph(checkpointer=None, store=None)
        if graph:
            print("   ? [LANGGRAPH] State graph compiled successfully!")
        else:
            print("   ? [LANGGRAPH ERROR] Graph instance returned None.")
    except Exception as exc:
        print(f"   ? [LANGGRAPH ERROR] Graph compilation failed: {exc}")

    print("\n" + "=" * 60)
    print("?? [DIAGNOSTICS COMPLETE]")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(run_diagnostics())
