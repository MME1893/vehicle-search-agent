import asyncio

import pytest

from scripts.research_all_vehicles import run_batch


@pytest.mark.asyncio
async def test_batch_command_processes_all_vehicles_with_bounded_concurrency():
    active = 0
    maximum_active = 0
    processed = []
    closed = 0

    class Worker:
        async def process(self, vehicle_id: int) -> str:
            nonlocal active, maximum_active
            active += 1
            maximum_active = max(maximum_active, active)
            await asyncio.sleep(0.01)
            processed.append(vehicle_id)
            active -= 1
            if vehicle_id == 3:
                return "needs_review"
            if vehicle_id == 4:
                return "failed"
            return "completed"

        async def close(self) -> None:
            nonlocal closed
            closed += 1

    summary = await run_batch([1, 2, 3, 4, 5], 2, lambda _number: Worker())

    assert sorted(processed) == [1, 2, 3, 4, 5]
    assert maximum_active == 2
    assert closed == 2
    assert summary.total == 5
    assert summary.completed == 3
    assert summary.needs_review == 1
    assert summary.failed == 1


@pytest.mark.asyncio
async def test_batch_command_rejects_invalid_concurrency():
    with pytest.raises(ValueError, match="at least 1"):
        await run_batch([1], 0, lambda _number: None)
