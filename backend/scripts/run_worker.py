import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.workers.agent_worker import run_agent_job


async def main():
    print(await run_agent_job())


if __name__ == "__main__":
    asyncio.run(main())
