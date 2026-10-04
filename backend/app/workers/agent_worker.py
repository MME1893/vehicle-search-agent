import inspect
import logging

from app.agents.errors import ResearchProviderError
from app.agents.factory import create_research_provider
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.repositories.agent_job_repository import AgentJobRepository
from app.services.research import ResearchService

logger = logging.getLogger(__name__)


class AgentWorker:
    """Claim and execute one pending vehicle-research job."""

    def __init__(self, jobs: AgentJobRepository, research_service: ResearchService):
        self.jobs = jobs
        self.research_service = research_service

    async def run_once(self, job_id: int | None = None):
        job = (
            self.jobs.get_pending_for_update(job_id)
            if job_id is not None
            else self.jobs.get_next_pending()
        )
        if job is None:
            logger.info("No pending agent job found job_id=%s", job_id)
            return None

        self.jobs.mark_running(job)
        logger.info("Agent job started job_id=%s vehicle_id=%s", job.id, job.vehicle_id)

        def update_step(step: str) -> None:
            if getattr(job, "current_step", None) != step:
                self.jobs.update_step(job, step)

        try:
            logger.info(
                "Agent research execution started job_id=%s vehicle_id=%s",
                job.id,
                job.vehicle_id,
            )
            await self.research_service.execute_vehicle_research(
                job.vehicle_id,
                persist=True,
                progress_callback=update_step,
            )
            completed = self.jobs.mark_completed(job)
            logger.info("Agent job completed job_id=%s", job.id)
            return completed
        except (ResearchProviderError, LookupError) as exc:
            logger.warning("Agent job failed job_id=%s error=%s", job.id, exc)
            self._rollback()
            return self.jobs.mark_failed(job, str(exc))
        except Exception as exc:
            logger.exception("Unexpected agent job failure job_id=%s", job.id)
            self._rollback()
            message = str(exc) or "unexpected internal research error"
            return self.jobs.mark_failed(job, message)

    def _rollback(self) -> None:
        db = getattr(self.jobs, "db", None)
        if db is not None:
            db.rollback()


async def run_agent_job(job_id: int | None = None):
    """Background-task entry point with its own database session."""

    logger.info("Agent job background task started job_id=%s", job_id)
    db = SessionLocal()
    provider = None
    jobs = AgentJobRepository(db)
    try:
        settings = get_settings()
        logger.info(
            "Initializing research provider job_id=%s provider=%s",
            job_id,
            settings.research_provider,
        )
        provider = create_research_provider(settings)
        logger.info(
            "Research provider initialized job_id=%s provider=%s",
            job_id,
            getattr(provider, "provider_name", type(provider).__name__),
        )
        service = ResearchService(db, provider, settings)
        return await AgentWorker(jobs, service).run_once(job_id)
    except Exception as exc:
        logger.exception("Unable to execute agent job job_id=%s", job_id)
        db.rollback()
        job = (
            jobs.get_by_id(job_id)
            if job_id is not None
            else jobs.get_next_pending()
        )
        if job is not None and job.status in {"PENDING", "RUNNING"}:
            if job.status == "PENDING":
                jobs.mark_running(job)
                logger.info(
                    "Agent job started job_id=%s vehicle_id=%s",
                    job.id,
                    job.vehicle_id,
                )
            message = str(exc) or "agent worker initialization failed"
            failed = jobs.mark_failed(job, message)
            logger.error("Agent job failed job_id=%s error=%s", job.id, message)
            return failed
        return None
    finally:
        close = getattr(getattr(provider, "client", None), "aclose", None)
        if close is not None:
            try:
                result = close()
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.exception(
                    "Unable to close research provider job_id=%s", job_id
                )
        db.close()
