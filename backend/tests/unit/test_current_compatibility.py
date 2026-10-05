from datetime import UTC, datetime, timedelta

from app.models import ResearchRun
from app.repositories.compatibility_repository import CompatibilityRepository
from app.repositories.engine_oil_repository import EngineOilRepository
from app.repositories.vehicle_repository import VehicleRepository


def _run(db, vehicle_id, status, when):
    run = ResearchRun(
        vehicle_id=vehicle_id,
        provider="test",
        matching_strategy="deterministic",
        research_status="FOUND",
        evaluation_status=status,
        evaluation_reason="test",
        started_at=when,
        completed_at=when,
        total_duration_ms=1,
        created_at=when,
    )
    db.add(run)
    db.flush()
    return run


def _event(repo, vehicle_id, oil_id, *, run=None, when=None, score=80):
    return repo.create_event(
        {
            "vehicle_id": vehicle_id,
            "engine_oil_id": oil_id,
            "research_run_id": run.id if run else None,
            "match_method": "DETERMINISTIC_SPEC_MATCH" if run else "MANUAL",
            "compatibility_type": "COMPATIBLE",
            "match_score": score,
            "confidence_score": 0.8,
            "created_by": "AGENT" if run else "ADMIN",
            "created_at": when,
        }
    )


def _fixture(db):
    vehicle = VehicleRepository(db).create({"manufacturer": "M", "model": "V"})
    oils = [
        EngineOilRepository(db).create(
            {"brand": "B", "name": name, "sae_viscosity": "5W-40", "oem_approvals": []}
        )
        for name in ("A", "B", "C")
    ]
    return vehicle, oils, CompatibilityRepository(db)


def test_latest_accepted_run_is_complete_current_snapshot_in_both_directions(db):
    vehicle, (oil_a, oil_b, oil_c), repo = _fixture(db)
    now = datetime.now(UTC)
    first = _run(db, vehicle.id, "ACCEPTED", now)
    _event(repo, vehicle.id, oil_a.id, run=first, when=now)
    _event(repo, vehicle.id, oil_b.id, run=first, when=now)
    second = _run(db, vehicle.id, "ACCEPTED", now + timedelta(hours=1))
    _event(repo, vehicle.id, oil_b.id, run=second, when=now + timedelta(hours=1))
    _event(repo, vehicle.id, oil_c.id, run=second, when=now + timedelta(hours=1))
    review = _run(db, vehicle.id, "NEEDS_REVIEW", now + timedelta(hours=2))
    _event(repo, vehicle.id, oil_a.id, run=review, when=now + timedelta(hours=2))

    assert {event.engine_oil_id for event in repo.get_current_for_vehicle(vehicle.id)} == {
        oil_b.id,
        oil_c.id,
    }
    assert repo.get_current_for_oil(oil_a.id) == []
    assert [event.vehicle_id for event in repo.get_current_for_oil(oil_c.id)] == [vehicle.id]


def test_manual_events_before_snapshot_are_superseded_and_later_latest_wins(db):
    vehicle, (oil_a, oil_b, _), repo = _fixture(db)
    now = datetime.now(UTC)
    _event(repo, vehicle.id, oil_a.id, when=now - timedelta(hours=1), score=10)
    run = _run(db, vehicle.id, "ACCEPTED", now)
    snapshot_b = _event(repo, vehicle.id, oil_b.id, run=run, when=now)
    first_override = _event(repo, vehicle.id, oil_b.id, when=now + timedelta(minutes=1), score=60)
    latest_override = _event(repo, vehicle.id, oil_b.id, when=now + timedelta(minutes=2), score=90)
    added_a = _event(repo, vehicle.id, oil_a.id, when=now + timedelta(minutes=3), score=70)

    current = {event.engine_oil_id: event for event in repo.get_current_for_vehicle(vehicle.id)}
    assert current == {oil_a.id: added_a, oil_b.id: latest_override}
    assert snapshot_b.id != current[oil_b.id].id
    assert first_override.id != current[oil_b.id].id


def test_without_accepted_run_latest_manual_event_per_pair_is_current(db):
    vehicle, (oil_a, _, _), repo = _fixture(db)
    now = datetime.now(UTC)
    _event(repo, vehicle.id, oil_a.id, when=now, score=20)
    latest = _event(repo, vehicle.id, oil_a.id, when=now + timedelta(seconds=1), score=90)
    assert repo.get_current_for_vehicle(vehicle.id) == [latest]
