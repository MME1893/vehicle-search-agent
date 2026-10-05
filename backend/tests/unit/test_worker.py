from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import AgentJob, Compatibility, EngineOil, ResearchRun
from app.repositories.agent_job_repository import AgentJobRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.research import ResearchService
from app.research.providers.openrouter.client import OpenRouterProviderError
from app.research.schemas import EngineOilResearchResult, ResearchExecution
from app.workers import agent_worker
from app.workers.agent_worker import AgentWorker


def job():
    return SimpleNamespace(
        id=7,
        vehicle_id=3,
        status="PENDING",
        current_step=None,
        attempts=0,
        started_at=None,
    )


def jobs_for(item):
    jobs = MagicMock()
    jobs.db = MagicMock()
    jobs.get_next_pending.return_value = item

    def mark_running(target):
        target.status = "RUNNING"
        target.current_step = "loading_vehicle"
        target.attempts += 1
        return target

    def update_step(target, step):
        target.current_step = step
        return target

    def mark_completed(target):
        target.status = "COMPLETED"
        target.current_step = "completed"
        return target

    def mark_failed(target, message):
        target.status = "FAILED"
        target.status_reason = message
        return target

    jobs.mark_running.side_effect = mark_running
    jobs.update_step.side_effect = update_step
    jobs.mark_completed.side_effect = mark_completed
    jobs.mark_failed.side_effect = mark_failed
    return jobs


@pytest.mark.asyncio
async def test_worker_picks_pending_job_and_completes_research():
    item = job()
    jobs = jobs_for(item)
    outcome = SimpleNamespace(evaluation=SimpleNamespace(accepted=True))

    async def execute(vehicle_id, *, persist, progress_callback):
        assert vehicle_id == item.vehicle_id
        assert persist is True
        for step in ("loading_vehicle", "researching", "evaluating", "saving", "matching"):
            progress_callback(step)
        return outcome

    research = MagicMock()
    research.execute_vehicle_research = AsyncMock(side_effect=execute)

    result = await AgentWorker(jobs, research).run_once()

    jobs.get_next_pending.assert_called_once_with()
    jobs.mark_running.assert_called_once_with(item)
    assert [call.args[1] for call in jobs.update_step.call_args_list] == [
        "researching",
        "evaluating",
        "saving",
        "matching",
    ]
    jobs.mark_completed.assert_called_once_with(item)
    assert item.attempts == 1
    assert item.status == "COMPLETED"
    assert item.current_step == "completed"
    assert result is item


@pytest.mark.asyncio
async def test_worker_marks_provider_error_failed():
    item = job()
    jobs = jobs_for(item)
    research = MagicMock()
    research.execute_vehicle_research = AsyncMock(
        side_effect=OpenRouterProviderError("OpenRouter connection failed")
    )

    result = await AgentWorker(jobs, research).run_once()

    jobs.mark_running.assert_called_once_with(item)
    jobs.mark_failed.assert_called_once_with(item, "OpenRouter connection failed")
    assert item.attempts == 1
    assert item.status == "FAILED"
    assert item.status_reason == "OpenRouter connection failed"
    assert result is item


@pytest.mark.asyncio
async def test_worker_returns_none_when_no_pending_job():
    jobs = MagicMock()
    jobs.get_next_pending.return_value = None

    result = await AgentWorker(jobs, MagicMock()).run_once()

    assert result is None
    jobs.mark_running.assert_not_called()


@pytest.mark.asyncio
async def test_background_job_uses_own_session_and_completes(db, monkeypatch):
    vehicle = VehicleRepository(db).create({"manufacturer": "M", "model": "V"})
    pending = AgentJobRepository(db).create({"vehicle_id": vehicle.id})
    background_session = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    opened_sessions = []

    def open_session():
        session = background_session()
        opened_sessions.append(session)
        return session

    class FakeProvider:
        provider_name = "fake"

    class FakeResearchService:
        def __init__(self, session, provider, settings):
            assert session is not db
            assert isinstance(provider, FakeProvider)

        async def execute_vehicle_research(
            self, vehicle_id, *, persist, progress_callback
        ):
            assert vehicle_id == vehicle.id
            assert persist is True
            progress_callback("researching")

    monkeypatch.setattr(agent_worker, "SessionLocal", open_session)
    monkeypatch.setattr(
        agent_worker,
        "get_settings",
        lambda: SimpleNamespace(research_provider="fake"),
    )
    monkeypatch.setattr(
        agent_worker, "create_research_provider", lambda settings: FakeProvider()
    )
    monkeypatch.setattr(agent_worker, "ResearchService", FakeResearchService)

    result = await agent_worker.run_agent_job(pending.id)

    db.expire_all()
    saved = db.get(AgentJob, pending.id)
    assert result.status == "COMPLETED"
    assert saved.status == "COMPLETED"
    assert saved.started_at is not None
    assert saved.completed_at is not None
    assert saved.attempts == 1
    assert opened_sessions


@pytest.mark.asyncio
async def test_background_initialization_failure_is_stored(db, monkeypatch):
    vehicle = VehicleRepository(db).create({"manufacturer": "M", "model": "V"})
    pending = AgentJobRepository(db).create({"vehicle_id": vehicle.id})
    background_session = sessionmaker(bind=db.get_bind(), expire_on_commit=False)

    monkeypatch.setattr(agent_worker, "SessionLocal", background_session)
    monkeypatch.setattr(
        agent_worker,
        "get_settings",
        lambda: SimpleNamespace(research_provider="broken"),
    )

    def fail_provider(settings):
        raise RuntimeError("provider initialization failed")

    monkeypatch.setattr(agent_worker, "create_research_provider", fail_provider)

    result = await agent_worker.run_agent_job(pending.id)

    db.expire_all()
    saved = db.get(AgentJob, pending.id)
    assert result.status == "FAILED"
    assert saved.status == "FAILED"
    assert saved.started_at is not None
    assert saved.completed_at is not None
    assert saved.attempts == 1
    assert saved.status_reason == "provider initialization failed"


@pytest.mark.asyncio
async def test_progress_commit_cannot_commit_partial_research_transaction(
    tmp_path, monkeypatch
):
    engine = create_engine(f"sqlite:///{tmp_path / 'worker.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as seed:
        vehicle = VehicleRepository(seed).create(
            {"manufacturer": "M", "model": "V", "engine_code": "TU5"}
        )
        pending = AgentJobRepository(seed).create({"vehicle_id": vehicle.id})
        vehicle_id, job_id = vehicle.id, pending.id
        seed.commit()

    research = EngineOilResearchResult.model_validate(
        {
            "research_status": "FOUND",
            "vehicle_id": vehicle_id,
            "engine_code": "TU5",
            "recommended_sae": ["10W-40"],
            "minimum_api": "SL",
            "confidence": 0.95,
            "sources": [
                {
                    "title": "Manual",
                    "url": "https://example.test/manual",
                    "source_type": "OFFICIAL_MANUAL",
                    "supported_claims": ["SAE 10W-40", "API SL"],
                }
            ],
            "recommended_products": [
                {
                    "brand": "New Brand",
                    "name": "New Oil",
                    "sae_viscosity": "10W-40",
                    "api_spec": "SN",
                    "source_urls": ["https://example.test/oil"],
                }
            ],
        }
    )

    class Provider:
        provider_name = "test"

        async def research_vehicle_oil_spec(self, vehicle):
            return ResearchExecution(research=research, provider="test")

        async def aclose(self):
            return None

    class FailingResearchService(ResearchService):
        def persist_compatibilities(self, outcome):
            raise RuntimeError("compatibility persistence failed")

    opened = []

    def open_session():
        session = sessions()
        opened.append(session)
        return session

    monkeypatch.setattr(agent_worker, "SessionLocal", open_session)
    monkeypatch.setattr(
        agent_worker, "get_settings", lambda: SimpleNamespace(research_provider="test", matching_strategy="deterministic", research_min_confidence=0.8)
    )
    monkeypatch.setattr(agent_worker, "create_research_provider", lambda settings: Provider())
    monkeypatch.setattr(agent_worker, "ResearchService", FailingResearchService)

    result = await agent_worker.run_agent_job(job_id)

    assert len(opened) == 2 and opened[0] is not opened[1]
    with sessions() as check:
        assert check.get(AgentJob, job_id).status == "FAILED"
        assert check.query(ResearchRun).count() == 0
        assert check.query(EngineOil).count() == 0
        assert check.query(Compatibility).count() == 0
    assert result.status == "FAILED"
