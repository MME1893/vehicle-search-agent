from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.core.config import Settings
from app.domain.enums import ResearchStatus
from app.models import Compatibility, EngineOil, ResearchRun, Vehicle
from app.research.errors import (
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ResearchProviderError,
)
from app.research.key_pool import ProviderKeyPool, parse_key_pool
from app.research.schemas import EngineOilResearchResult, ResearchExecution
from scripts.research_provider_matrix import (
    LANES,
    LaneExecutor,
    calculate_lane_status,
    execute_lane,
    load_benchmark_settings,
    load_lane_status,
    parse_args,
    run,
    select_vehicle_ids,
)


def add_vehicles(db, ids=(10, 20, 30, 40, 50)):
    for vehicle_id in ids:
        db.add(
            Vehicle(
                id=vehicle_id,
                manufacturer="Peugeot",
                model=str(vehicle_id),
                engine_code="TU5",
                fuel_type="gasoline",
            )
        )
    db.commit()


def insufficient_execution(vehicle, provider, model):
    return ResearchExecution(
        research=EngineOilResearchResult(
            research_status=ResearchStatus.INSUFFICIENT,
            vehicle_id=vehicle.id,
            engine_code=vehicle.engine_code,
            confidence=0,
        ),
        provider=provider,
        model=model,
    )


def test_lane_is_required_for_execution_and_status_needs_batch():
    with pytest.raises(SystemExit):
        parse_args([])
    with pytest.raises(SystemExit):
        parse_args(["--status"])
    assert parse_args(["--lane", "gemini"]).lane == ["gemini"]
    assert parse_args(["--batch-id", "b", "--status"]).lane is None


def test_vehicle_selection_is_ordered_then_limited(db):
    add_vehicles(db, (40, 10, 30, 20))
    assert select_vehicle_ids(db, None, 3) == [10, 20, 30]
    assert select_vehicle_ids(db, [40, 10], None) == [10, 40]


def test_status_reports_gap_prefix_next_and_models():
    status = calculate_lane_status(
        "openrouter-apodex",
        [10, 20, 30, 40, 50],
        [(10, "apodex"), (20, "apodex"), (40, "fallback"), (50, "apodex")],
    )
    assert status.completed_vehicle_ids == [10, 20, 40, 50]
    assert status.highest_completed_vehicle_id == 50
    assert status.contiguous_through_vehicle_id == 20
    assert status.next_pending_vehicle_id == 30
    assert status.gaps_before_highest_completed == [30]
    assert status.actual_model_counts == {"apodex": 3, "fallback": 1}


def test_key_pool_plural_singular_disable_and_temporary_rotation():
    assert parse_key_pool(None, "one") == ["one"]
    assert parse_key_pool(" , ", "one") == ["one"]
    assert parse_key_pool(" one, two, one, ", "fallback") == ["one", "two"]
    pool = ProviderKeyPool(["secret-one", "secret-two"])
    assert [lease.index for lease in pool.available()] == [1, 2]
    # A temporary throttle does not mutate the pool.
    assert [lease.index for lease in pool.available()] == [1, 2]
    pool.disable(1)
    assert [lease.index for lease in pool.available()] == [2]
    assert "secret" not in repr([lease.index for lease in pool.available()])


@pytest.mark.asyncio
async def test_matrix_persists_only_research_run_and_resumes(db, monkeypatch):
    add_vehicles(db, (10,))

    class Provider:
        provider_name = "opencode"

        def __init__(self):
            self.client = SimpleNamespace(model="opencode/big-pickle")
            self.calls = 0

        async def research_vehicle_oil_spec(self, vehicle):
            self.calls += 1
            return insufficient_execution(
                vehicle, "opencode", "opencode/big-pickle"
            )

        async def aclose(self):
            pass

    providers = []

    def factory(_settings):
        provider = Provider()
        providers.append(provider)
        return provider

    monkeypatch.setattr(
        "scripts.research_provider_matrix.create_research_provider", factory
    )
    settings = Settings(research_provider="gemini")
    first = await execute_lane(
        db, settings, "batch-1", LANES["opencode-big-pickle"], [10]
    )
    assert first.failures == 0
    run = db.scalar(select(ResearchRun))
    assert (run.batch_id, run.batch_lane, run.model) == (
        "batch-1",
        "opencode-big-pickle",
        "opencode/big-pickle",
    )
    assert db.scalar(select(func.count(EngineOil.id))) == 0
    assert db.scalar(select(func.count(Compatibility.id))) == 0

    second = await execute_lane(
        db, settings, "batch-1", LANES["opencode-big-pickle"], [10]
    )
    assert second.by_model["opencode/big-pickle"]["skipped"] == 1
    assert sum(provider.calls for provider in providers) == 1


@pytest.mark.asyncio
async def test_permanent_bad_key_is_disabled_and_secret_is_not_printed(
    db, monkeypatch, capsys
):
    add_vehicles(db, (10, 20))
    attempts = []

    class Provider:
        def __init__(self, key, model):
            self.key = key
            self.model = model

        async def research_vehicle_oil_spec(self, vehicle):
            attempts.append((vehicle.id, self.key))
            if self.key == "very-secret-bad-key":
                raise ProviderAuthenticationError("Gemini authentication failed")
            return insufficient_execution(vehicle, "gemini", self.model)

        async def aclose(self):
            pass

    monkeypatch.setattr(
        "scripts.research_provider_matrix.create_research_provider",
        lambda settings: Provider(settings.gemini_api_key, settings.gemini_model),
    )
    settings = Settings(
        gemini_api_keys="very-secret-bad-key,very-secret-good-key"
    )
    summary = await execute_lane(db, settings, "keys", LANES["gemini"], [10, 20])
    assert summary.failures == 0
    assert attempts == [
        (10, "very-secret-bad-key"),
        (10, "very-secret-good-key"),
        (20, "very-secret-good-key"),
    ]
    output = capsys.readouterr().out
    assert "very-secret" not in output


@pytest.mark.asyncio
async def test_openrouter_rate_limit_rotates_key_without_disabling_it(db, monkeypatch):
    add_vehicles(db, (10,))
    attempts = []

    class Provider:
        def __init__(self, key, model):
            self.key = key
            self.model = model

        async def research_vehicle_oil_spec(self, vehicle):
            attempts.append(self.key)
            if self.key == "key-one":
                raise ProviderRateLimitError("OpenRouter rate limit exceeded")
            return insufficient_execution(vehicle, "openrouter", self.model)

        async def aclose(self):
            pass

    monkeypatch.setattr(
        "scripts.research_provider_matrix.create_research_provider",
        lambda settings: Provider(settings.openrouter_api_key, settings.openrouter_model),
    )
    executor = LaneExecutor(
        LANES["openrouter-apodex"],
        Settings(openrouter_api_keys="key-one,key-two"),
        db,
    )
    try:
        outcome, key_index, _provider = await executor.research("batch", 10)
    finally:
        await executor.close()

    assert outcome.execution.model == LANES["openrouter-apodex"].primary_model
    assert key_index == 2
    assert attempts == ["key-one", "key-two"]
    assert not executor.key_pool.is_disabled(1)


@pytest.mark.asyncio
async def test_openrouter_all_rate_limited_keys_raise_last_rate_limit(db, monkeypatch):
    add_vehicles(db, (10,))
    attempts = []

    class Provider:
        def __init__(self, key):
            self.key = key

        async def research_vehicle_oil_spec(self, _vehicle):
            attempts.append(self.key)
            raise ProviderRateLimitError("OpenRouter rate limit exceeded")

        async def aclose(self):
            pass

    monkeypatch.setattr(
        "scripts.research_provider_matrix.create_research_provider",
        lambda settings: Provider(settings.openrouter_api_key),
    )
    executor = LaneExecutor(
        LANES["openrouter-apodex"],
        Settings(openrouter_api_keys="key-one,key-two"),
        db,
    )
    try:
        with pytest.raises(ProviderRateLimitError, match="rate limit exceeded"):
            await executor.research("batch", 10)
    finally:
        await executor.close()

    assert attempts == ["key-one", "key-two"]
    assert not executor.key_pool.is_disabled(1)
    assert not executor.key_pool.is_disabled(2)


@pytest.mark.asyncio
@pytest.mark.parametrize("lane_name", ["openrouter-apodex", "openrouter-dots"])
async def test_openrouter_primary_failure_does_not_construct_fallback(
    db, monkeypatch, capsys, lane_name
):
    add_vehicles(db, (10,))
    constructed = []

    class Provider:
        def __init__(self, model):
            self.model = model

        async def research_vehicle_oil_spec(self, vehicle):
            raise ResearchProviderError("primary model unavailable")

        async def aclose(self):
            pass

    def factory(settings):
        constructed.append(
            (settings.openrouter_model, settings.openrouter_resin_account)
        )
        return Provider(settings.openrouter_model)

    monkeypatch.setattr(
        "scripts.research_provider_matrix.create_research_provider", factory
    )
    settings = Settings(openrouter_api_key="secret")
    summary = await execute_lane(db, settings, "primary-only", LANES[lane_name], [10])
    assert summary.failures == 1
    assert db.scalar(select(ResearchRun)) is None
    assert constructed == [
        (LANES[lane_name].primary_model, lane_name),
    ]
    assert "error=primary model unavailable" in capsys.readouterr().out


def test_separate_lanes_have_independent_status(db):
    add_vehicles(db, (10, 20))
    common = {
        "vehicle_id": 10,
        "provider": "gemini",
        "model": "gemini-2.5-flash",
        "matching_strategy": "deterministic",
        "research_status": "INSUFFICIENT",
        "evaluation_status": "REJECTED",
        "evaluation_reason": "insufficient",
        "search_queries": [],
        "grounding_sources": [],
        "started_at": datetime.now(UTC),
        "completed_at": datetime.now(UTC),
        "total_duration_ms": 1,
        "batch_id": "batch-1",
    }
    db.add(ResearchRun(**common, batch_lane="gemini"))
    db.commit()
    gemini = load_lane_status(db, "batch-1", "gemini", [10, 20])
    apodex = load_lane_status(db, "batch-1", "openrouter-apodex", [10, 20])
    assert gemini.completed_vehicle_ids == [10]
    assert apodex.completed_vehicle_ids == []


@pytest.mark.asyncio
async def test_status_is_read_only_and_initializes_no_provider(
    db, monkeypatch, capsys
):
    add_vehicles(db, (10, 20))
    monkeypatch.setattr(
        "scripts.research_provider_matrix.load_benchmark_settings", lambda: Settings()
    )
    monkeypatch.setattr(
        "scripts.research_provider_matrix.create_script_session", lambda: (db, None)
    )
    provider_factory = AsyncMock()
    monkeypatch.setattr(
        "scripts.research_provider_matrix.create_research_provider", provider_factory
    )
    args = SimpleNamespace(
        batch_id="status-batch",
        lane=None,
        limit=None,
        vehicle_id=None,
        status=True,
    )
    before = db.scalar(select(func.count(ResearchRun.id)))
    assert await run(args) == 0
    after = db.scalar(select(func.count(ResearchRun.id)))
    assert before == after == 0
    provider_factory.assert_not_called()
    output = capsys.readouterr().out
    for lane_name in LANES:
        assert f"lane: {lane_name}" in output


def test_benchmark_settings_ignore_incompatible_operational_pair(monkeypatch):
    monkeypatch.setenv("RESEARCH_PROVIDER", "opencode")
    monkeypatch.setenv("MATCHING_STRATEGY", "provider_catalog")
    settings = load_benchmark_settings()
    assert settings.research_provider == "gemini"
    assert settings.matching_strategy == "deterministic"
