import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.factory import create_research_provider
from app.agents.gemini_research_adapter import GeminiResearchAdapter
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.repositories.agent_job_repository import AgentJobRepository
from app.services.research import ResearchService
from app.workers.compatibility_worker import CompatibilityWorker


async def main():
    settings = get_settings()
    db = SessionLocal()
    provider = None
    try:
        provider = create_research_provider(settings)
        worker = CompatibilityWorker(
            AgentJobRepository(db), ResearchService(db, provider, settings)
        )
        print(await worker.run_once())
    finally:
        if isinstance(provider, GeminiResearchAdapter):
            await provider.client.aclose()
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
