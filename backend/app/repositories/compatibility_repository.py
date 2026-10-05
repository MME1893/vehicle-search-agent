from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Compatibility, ResearchRun, Vehicle


class CompatibilityRepository:
    """Append-only compatibility events plus the canonical current-state projection."""

    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, ident: int) -> Compatibility | None:
        return self.db.get(Compatibility, ident)

    def create_event(self, data: dict) -> Compatibility:
        event = Compatibility(**data)
        self.db.add(event)
        self.db.flush()
        self.db.refresh(event)
        return event

    def _latest_accepted_run(self, vehicle_id: int) -> ResearchRun | None:
        return self.db.scalar(
            select(ResearchRun)
            .where(
                ResearchRun.vehicle_id == vehicle_id,
                ResearchRun.evaluation_status == "ACCEPTED",
            )
            .order_by(
                ResearchRun.completed_at.desc().nullslast(),
                ResearchRun.created_at.desc(),
                ResearchRun.id.desc(),
            )
            .limit(1)
        )

    def get_current_for_vehicle(self, vehicle_id: int) -> list[Compatibility]:
        run = self._latest_accepted_run(vehicle_id)
        current: dict[int, Compatibility] = {}
        if run is not None:
            snapshot = self.db.scalars(
                select(Compatibility).where(Compatibility.research_run_id == run.id)
            )
            current.update((event.engine_oil_id, event) for event in snapshot)

        manual_query = select(Compatibility).where(
            Compatibility.vehicle_id == vehicle_id,
            Compatibility.research_run_id.is_(None),
            Compatibility.match_method == "MANUAL",
        )
        if run is not None:
            manual_query = manual_query.where(Compatibility.created_at > run.created_at)
        manual_events = self.db.scalars(
            manual_query.order_by(Compatibility.created_at.desc(), Compatibility.id.desc())
        )
        manually_touched: set[int] = set()
        for event in manual_events:
            if event.engine_oil_id not in manually_touched:
                current[event.engine_oil_id] = event
                manually_touched.add(event.engine_oil_id)
        return sorted(
            current.values(), key=lambda event: (event.created_at, event.id), reverse=True
        )

    def get_current_for_oil(self, oil_id: int) -> list[Compatibility]:
        vehicle_ids = self.db.scalars(select(Vehicle.id).order_by(Vehicle.id))
        return [
            event
            for vehicle_id in vehicle_ids
            for event in self.get_current_for_vehicle(vehicle_id)
            if event.engine_oil_id == oil_id
        ]

    def get_for_research_runs(self, run_ids: list[int]) -> list[Compatibility]:
        if not run_ids:
            return []
        return list(
            self.db.scalars(
                select(Compatibility)
                .where(Compatibility.research_run_id.in_(run_ids))
                .order_by(Compatibility.created_at, Compatibility.id)
            )
        )
