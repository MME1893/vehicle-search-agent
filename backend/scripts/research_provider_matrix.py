import argparse
import asyncio
import inspect
import sys
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import Settings
from app.core.logging import configure_logging
from app.models import ResearchRun, Vehicle
from app.research import ResearchService
from app.research.errors import (
    ProviderAuthenticationError,
    ProviderQuotaError,
    ProviderRateLimitError,
    ResearchProviderError,
)
from app.research.factory import create_research_provider
from app.research.key_pool import ProviderKeyPool, parse_key_pool
from scripts.research_vehicle import create_script_session


@dataclass(frozen=True)
class Lane:
    name: str
    provider: str
    primary_model: str


LANES = {
    lane.name: lane
    for lane in (
        Lane("gemini", "gemini", "gemini-2.5-flash"),
        Lane(
            "openrouter-apodex",
            "openrouter",
            "apodex/apodex-1.1-mini:free",
        ),
        Lane(
            "openrouter-dots",
            "openrouter",
            "dots-studio/dots-3-note-preview:free",
        ),
        Lane("opencode-big-pickle", "opencode", "opencode/big-pickle"),
        Lane(
            "opencode-exo",
            "opencode",
            "opencode/exo-free",
        ),
        Lane(
            "opencode-fledge-alpha",
            "opencode",
            "opencode/fledge-alpha-free",
        ),
        Lane(
            "opencode-ling-3.0-flash-fin",
            "opencode",
            "opencode/ling-3.0-flash-fin-free",
        ),
        Lane(
            "opencode-ling-3.1-flash",
            "opencode",
            "opencode/ling-3.1-flash-free",
        ),
        Lane(
            "opencode-longcat-2.5-preview",
            "opencode",
            "opencode/longcat-2.5-preview-free",
        ),
        Lane(
            "opencode-mimo-v2.6-flash",
            "opencode",
            "opencode/mimo-v2.6-flash-free",
        ),
        Lane(
            "opencode-muse-spark-1.3",
            "opencode",
            "opencode/muse-spark-1.3-contributor-free",
        ),
        Lane(
            "opencode-nemotron-3-ultra",
            "opencode",
            "opencode/nemotron-3-ultra-free",
        ),
        Lane(
            "opencode-nemotron-3.5-lightning",
            "opencode",
            "opencode/nemotron-3.5-lightning-free",
        ),
        Lane(
            "opencode-space-bunny",
            "opencode",
            "opencode/space-bunny-free",
        )
    )
}


@dataclass(frozen=True)
class LaneStatus:
    lane: str
    completed_vehicle_ids: list[int]
    total_vehicle_count: int
    highest_completed_vehicle_id: int | None
    contiguous_through_vehicle_id: int | None
    next_pending_vehicle_id: int | None
    gaps_before_highest_completed: list[int]
    actual_model_counts: dict[str, int]

    @property
    def completed_count(self) -> int:
        return len(self.completed_vehicle_ids)

    @property
    def remaining_count(self) -> int:
        return self.total_vehicle_count - self.completed_count


@dataclass
class ExecutionSummary:
    lane: str
    by_model: dict[str, Counter] = field(
        default_factory=lambda: defaultdict(Counter)
    )

    def add(self, model: str, status: str) -> None:
        self.by_model[model][status] += 1

    @property
    def failures(self) -> int:
        return sum(counts["failed"] for counts in self.by_model.values())


def generated_batch_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"benchmark-{stamp}-{uuid.uuid4().hex[:6]}"


def load_benchmark_settings() -> Settings:
    """Load env configuration without applying unrelated operational pairing."""
    return Settings(research_provider="gemini", matching_strategy="deterministic")


def select_vehicle_ids(db, vehicle_ids: list[int] | None, limit: int | None) -> list[int]:
    statement = select(Vehicle.id)
    if vehicle_ids:
        statement = statement.where(Vehicle.id.in_(set(vehicle_ids)))
    statement = statement.order_by(Vehicle.id)
    if limit is not None:
        statement = statement.limit(limit)
    return list(db.scalars(statement))


def compact_ids(vehicle_ids: list[int]) -> str:
    if not vehicle_ids:
        return "none"
    ranges: list[str] = []
    start = previous = vehicle_ids[0]
    for vehicle_id in vehicle_ids[1:]:
        if vehicle_id == previous + 1:
            previous = vehicle_id
            continue
        ranges.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = vehicle_id
    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    return ", ".join(ranges)


def calculate_lane_status(
    lane: str,
    ordered_vehicle_ids: list[int],
    completed_rows: list[tuple[int, str | None]],
) -> LaneStatus:
    applicable = set(ordered_vehicle_ids)
    completed = sorted({vehicle_id for vehicle_id, _ in completed_rows} & applicable)
    completed_set = set(completed)
    highest = max(completed) if completed else None
    prefix: list[int] = []
    for vehicle_id in ordered_vehicle_ids:
        if vehicle_id not in completed_set:
            break
        prefix.append(vehicle_id)
    next_pending = next(
        (vehicle_id for vehicle_id in ordered_vehicle_ids if vehicle_id not in completed_set),
        None,
    )
    gaps = (
        [
            vehicle_id
            for vehicle_id in ordered_vehicle_ids
            if vehicle_id < highest and vehicle_id not in completed_set
        ]
        if highest is not None
        else []
    )
    models = Counter(
        model
        for vehicle_id, model in completed_rows
        if vehicle_id in applicable and model
    )
    return LaneStatus(
        lane=lane,
        completed_vehicle_ids=completed,
        total_vehicle_count=len(ordered_vehicle_ids),
        highest_completed_vehicle_id=highest,
        contiguous_through_vehicle_id=prefix[-1] if prefix else None,
        next_pending_vehicle_id=next_pending,
        gaps_before_highest_completed=gaps,
        actual_model_counts=dict(sorted(models.items())),
    )


def load_lane_status(db, batch_id: str, lane: str, vehicle_ids: list[int]) -> LaneStatus:
    rows = list(
        db.execute(
            select(ResearchRun.vehicle_id, ResearchRun.model).where(
                ResearchRun.batch_id == batch_id,
                ResearchRun.batch_lane == lane,
                ResearchRun.vehicle_id.in_(vehicle_ids) if vehicle_ids else False,
            )
        )
    )
    return calculate_lane_status(lane, vehicle_ids, rows)


def _display_id(value: int | None) -> str:
    return "none" if value is None else str(value)


def print_status(batch_id: str, statuses: list[LaneStatus]) -> None:
    print(f"batch: {batch_id}")
    for status in statuses:
        print(f"\nlane: {status.lane}")
        print(f"completed: {status.completed_count} / {status.total_vehicle_count}")
        print(f"remaining: {status.remaining_count}")
        print(f"completed_count: {status.completed_count}")
        print(f"total_vehicle_count: {status.total_vehicle_count}")
        print(f"remaining_count: {status.remaining_count}")
        print(f"completed_vehicle_ids: {compact_ids(status.completed_vehicle_ids)}")
        print(
            "highest_completed_vehicle_id: "
            + _display_id(status.highest_completed_vehicle_id)
        )
        print(
            "contiguous_through_vehicle_id: "
            + _display_id(status.contiguous_through_vehicle_id)
        )
        print("next_pending_vehicle_id: " + _display_id(status.next_pending_vehicle_id))
        print(f"gaps_before_highest_completed: {compact_ids(status.gaps_before_highest_completed)}")
        if status.actual_model_counts:
            print("actual_models:")
            for model, count in status.actual_model_counts.items():
                print(f"  {model}: {count}")
            print(
                "actual_model_counts: "
                + ", ".join(
                    f"{model}={count}"
                    for model, count in status.actual_model_counts.items()
                )
            )
        else:
            print("actual_models: none")
            print("actual_model_counts: none")


class LaneExecutor:
    def __init__(self, lane: Lane, settings: Settings, db):
        self.lane = lane
        self.settings = settings
        self.db = db
        self.providers: dict[tuple[str, int], object] = {}
        if lane.provider == "gemini":
            keys = parse_key_pool(settings.gemini_api_keys, settings.gemini_api_key)
        elif lane.provider == "openrouter":
            keys = parse_key_pool(
                settings.openrouter_api_keys, settings.openrouter_api_key
            )
        else:
            keys = [""]
        self.key_pool = ProviderKeyPool(keys)

    def _provider(self, model: str, key_index: int, key: str):
        cache_key = (model, key_index)
        if cache_key in self.providers:
            return self.providers[cache_key]
        updates = {
            "research_provider": self.lane.provider,
            "matching_strategy": "deterministic",
        }
        if self.lane.provider == "gemini":
            updates.update(gemini_model=model, gemini_api_key=key)
        elif self.lane.provider == "openrouter":
            updates.update(
                openrouter_model=model,
                openrouter_api_key=key,
                openrouter_resin_account=self.lane.name,
            )
        else:
            updates.update(opencode_model=model)
        provider = create_research_provider(self.settings.model_copy(update=updates))
        self.providers[cache_key] = provider
        return provider

    async def _try_model(self, vehicle_id: int, model: str):
        leases = self.key_pool.available()
        if not leases:
            raise ResearchProviderError(
                f"no usable {self.lane.provider} credentials are configured"
            )
        last_error: Exception | None = None
        for lease in leases:
            provider = self._provider(model, lease.index, lease.key)
            service_settings = self.settings.model_copy(
                update={
                    "research_provider": self.lane.provider,
                    "matching_strategy": "deterministic",
                }
            )
            try:
                outcome = await ResearchService(
                    self.db, provider, service_settings
                ).research_vehicle(vehicle_id)
                return outcome, lease.index, provider
            except (ProviderAuthenticationError, ProviderQuotaError) as exc:
                self.db.rollback()
                self.key_pool.disable(lease.index)
                last_error = exc
            except ProviderRateLimitError as exc:
                self.db.rollback()
                last_error = exc
            except Exception:
                self.db.rollback()
                raise
        assert last_error is not None
        raise last_error

    async def research(self, batch_id: str, vehicle_id: int):
        return await self._try_model(vehicle_id, self.lane.primary_model)

    async def close(self) -> None:
        for provider in self.providers.values():
            close = getattr(provider, "aclose", None)
            if close is not None:
                result = close()
                if inspect.isawaitable(result):
                    await result


def _outcome_status(outcome) -> str:
    if outcome.result.research_status.value == "INSUFFICIENT":
        return "insufficient"
    if outcome.evaluation.accepted:
        return "accepted"
    return "needs_review"


def _short_error(exc: Exception, settings: Settings) -> str:
    message = " ".join(str(exc).split()) or exc.__class__.__name__
    secrets = parse_key_pool(settings.gemini_api_keys, settings.gemini_api_key)
    secrets += parse_key_pool(
        settings.openrouter_api_keys, settings.openrouter_api_key
    )
    for secret in secrets:
        message = message.replace(secret, "[REDACTED]")
    return message[:180]


async def execute_lane(
    db, settings: Settings, batch_id: str, lane: Lane, vehicle_ids: list[int]
) -> ExecutionSummary:
    summary = ExecutionSummary(lane.name)
    executor = LaneExecutor(lane, settings, db)
    try:
        for vehicle_id in vehicle_ids:
            existing = db.scalar(
                select(ResearchRun).where(
                    ResearchRun.batch_id == batch_id,
                    ResearchRun.vehicle_id == vehicle_id,
                    ResearchRun.batch_lane == lane.name,
                )
            )
            if existing:
                summary.add(existing.model or "unknown", "skipped")
                print(
                    f"batch={batch_id} vehicle={vehicle_id} lane={lane.name} "
                    f"provider={lane.provider} requested={lane.primary_model} "
                    f"actual={existing.model or 'unknown'} key=- status=SKIP "
                    f"duration=0.0s research_run={existing.id}",
                    flush=True,
                )
                continue
            started = time.perf_counter()
            try:
                outcome, key_index, provider = await executor.research(
                    batch_id, vehicle_id
                )
                outcome.research_run.batch_id = batch_id
                outcome.research_run.batch_lane = lane.name
                service = ResearchService(db, provider, settings)
                service.persist_research_run(outcome)
                db.commit()
                status = _outcome_status(outcome)
                summary.add(outcome.execution.model or "unknown", status)
                print(
                    f"batch={batch_id} vehicle={vehicle_id} lane={lane.name} "
                    f"provider={lane.provider} requested={lane.primary_model} "
                    f"actual={outcome.execution.model or 'unknown'} key={key_index} "
                    f"status=PASS outcome={status.upper()} "
                    f"duration={time.perf_counter() - started:.1f}s "
                    f"research_run={outcome.research_run.id}",
                    flush=True,
                )
            except Exception as exc:  # noqa: BLE001 - isolate each vehicle
                db.rollback()
                summary.add(lane.primary_model, "failed")
                print(
                    f"batch={batch_id} vehicle={vehicle_id} lane={lane.name} "
                    f"provider={lane.provider} requested={lane.primary_model} "
                    f"actual=- key=- status=FAILED "
                    f"duration={time.perf_counter() - started:.1f}s "
                    f"error={_short_error(exc, settings)}",
                    flush=True,
                )
    finally:
        await executor.close()
    return summary


def print_summary(summary: ExecutionSummary) -> None:
    print(f"\nsummary lane={summary.lane}")
    for model, counts in sorted(summary.by_model.items()):
        print(
            f"  actual_model={model} accepted={counts['accepted']} "
            f"needs_review={counts['needs_review']} "
            f"insufficient={counts['insufficient']} failed={counts['failed']} "
            f"skipped={counts['skipped']}"
        )


async def run(args) -> int:
    settings = load_benchmark_settings()
    configure_logging(settings.log_level)
    db, local_engine = create_script_session()
    try:
        vehicle_ids = select_vehicle_ids(db, args.vehicle_id, args.limit)
        if args.status:
            statuses = [
                load_lane_status(db, args.batch_id, lane_name, vehicle_ids)
                for lane_name in (args.lane or list(LANES))
            ]
            print_status(args.batch_id, statuses)
            return 0

        batch_id = args.batch_id or generated_batch_id()
        print(f"batch: {batch_id}", flush=True)
        failed = 0
        for lane_name in args.lane:
            summary = await execute_lane(
                db, settings, batch_id, LANES[lane_name], vehicle_ids
            )
            print_summary(summary)
            failed += summary.failures
        return 1 if failed else 0
    finally:
        db.close()
        if local_engine is not None:
            local_engine.dispose()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run or inspect the resumable research-provider benchmark matrix"
    )
    parser.add_argument("--batch-id")
    parser.add_argument("--lane", action="append", choices=list(LANES))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--vehicle-id", action="append", type=int)
    parser.add_argument("--status", action="store_true")
    return parser


def parse_args(argv: list[str] | None = None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.status and not args.lane:
        parser.error("at least one --lane is required unless --status is used")
    if args.status and not args.batch_id:
        parser.error("--batch-id is required with --status")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    return args


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(parse_args())))
