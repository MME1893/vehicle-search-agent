import argparse
import asyncio
import inspect
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.errors import ResearchProviderError
from app.agents.factory import create_research_provider
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.models import Vehicle
from app.services.research import ResearchService
from scripts.research_vehicle import create_script_session


class BatchWorker(Protocol):
    async def process(self, vehicle_id: int) -> str: ...

    async def close(self) -> None: ...


@dataclass(frozen=True)
class BatchSummary:
    total: int
    completed: int
    needs_review: int
    failed: int


class VehicleResearchWorker:
    """Owns one DB session and provider for one async queue consumer."""

    def __init__(self, settings: Settings):
        self.db, self.local_engine = create_script_session()
        self.provider = create_research_provider(settings)
        self.service = ResearchService(self.db, self.provider, settings)

    async def process(self, vehicle_id: int) -> str:
        try:
            outcome = await self.service.execute_vehicle_research(vehicle_id, persist=True)
            if outcome.evaluation.needs_review:
                print(f"vehicle_id={vehicle_id} status=NEEDS_REVIEW", flush=True)
                return "needs_review"
            saved = len(outcome.compatibility_ids)
            print(
                f"vehicle_id={vehicle_id} status=COMPLETED compatibilities={saved}",
                flush=True,
            )
            return "completed"
        except (ResearchProviderError, LookupError) as exc:
            self.db.rollback()
            print(f"vehicle_id={vehicle_id} status=FAILED error={exc}", flush=True)
            return "failed"
        except Exception as exc:  # noqa: BLE001 - one failure must not stop the batch
            self.db.rollback()
            print(
                f"vehicle_id={vehicle_id} status=FAILED error={exc.__class__.__name__}",
                flush=True,
            )
            return "failed"

    async def close(self) -> None:
        client = getattr(self.provider, "client", None)
        close = getattr(client, "aclose", None)
        if close is not None:
            result = close()
            if inspect.isawaitable(result):
                await result
        self.db.close()
        if self.local_engine is not None:
            self.local_engine.dispose()


async def run_batch(
    vehicle_ids: list[int],
    concurrency: int,
    worker_factory: Callable[[int], BatchWorker],
) -> BatchSummary:
    """Process every vehicle once using a bounded asyncio queue."""
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")
    if not vehicle_ids:
        return BatchSummary(total=0, completed=0, needs_review=0, failed=0)

    queue: asyncio.Queue[int] = asyncio.Queue()
    for vehicle_id in vehicle_ids:
        queue.put_nowait(vehicle_id)
    counts: Counter[str] = Counter()
    lock = asyncio.Lock()

    async def consume(worker_number: int) -> None:
        worker = worker_factory(worker_number)
        try:
            while True:
                try:
                    vehicle_id = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    status = await worker.process(vehicle_id)
                except Exception as exc:  # noqa: BLE001 - keep other queue items running
                    print(
                        f"vehicle_id={vehicle_id} status=FAILED "
                        f"error={exc.__class__.__name__}",
                        flush=True,
                    )
                    status = "failed"
                finally:
                    queue.task_done()
                async with lock:
                    counts[
                        status if status in {"completed", "needs_review"} else "failed"
                    ] += 1
        finally:
            await worker.close()

    worker_count = min(concurrency, len(vehicle_ids))
    await asyncio.gather(*(consume(index) for index in range(worker_count)))
    return BatchSummary(
        total=len(vehicle_ids),
        completed=counts["completed"],
        needs_review=counts["needs_review"],
        failed=counts["failed"],
    )


async def main(concurrency: int) -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    db, local_engine = create_script_session()
    try:
        vehicle_ids = list(db.scalars(select(Vehicle.id).order_by(Vehicle.id)))
    finally:
        db.close()
        if local_engine is not None:
            local_engine.dispose()

    print(
        f"Starting batch research: vehicles={len(vehicle_ids)} "
        f"concurrency={concurrency}",
        flush=True,
    )
    summary = await run_batch(
        vehicle_ids,
        concurrency,
        lambda _worker_number: VehicleResearchWorker(settings),
    )
    print(
        f"Finished: total={summary.total} completed={summary.completed} "
        f"needs_review={summary.needs_review} failed={summary.failed}",
        flush=True,
    )
    return 1 if summary.failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Research all stored vehicles")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=3,
        help="Number of concurrent research workers (default: 3)",
    )
    args = parser.parse_args()
    if args.concurrency < 1:
        parser.error("--concurrency must be at least 1")
    raise SystemExit(asyncio.run(main(args.concurrency)))
