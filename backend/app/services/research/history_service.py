from collections import defaultdict

from sqlalchemy import select

from app.models import CompatibilityHistory, EngineOil, EngineSpec, ResearchRun
from app.repositories.vehicle_repository import VehicleRepository
from app.schemas.research_history import (
    ResearchTimelineEntry,
    VehicleResearchHistory,
)


class ResearchHistoryService:
    """Builds the stored, read-only research timeline for one vehicle."""

    def __init__(self, db):
        self.db = db
        self.vehicles = VehicleRepository(db)

    def get_vehicle_history(self, vehicle_id: int) -> VehicleResearchHistory:
        vehicle = self.vehicles.get_by_id(vehicle_id)
        if vehicle is None:
            raise LookupError("vehicle not found")

        runs = list(
            self.db.scalars(
                select(ResearchRun)
                .where(ResearchRun.vehicle_id == vehicle_id)
                .order_by(ResearchRun.started_at, ResearchRun.id)
            )
        )
        if not runs:
            return VehicleResearchHistory(vehicle=vehicle, timeline=[])

        run_ids = [run.id for run in runs]
        specs_by_run = defaultdict(list)
        for spec in self.db.scalars(
            select(EngineSpec)
            .where(EngineSpec.research_run_id.in_(run_ids))
            .order_by(EngineSpec.created_at, EngineSpec.id)
        ):
            specs_by_run[spec.research_run_id].append(spec)

        history_by_run = defaultdict(list)
        histories = list(
            self.db.scalars(
                select(CompatibilityHistory)
                .where(
                    CompatibilityHistory.vehicle_id == vehicle_id,
                    CompatibilityHistory.research_run_id.in_(run_ids),
                )
                .order_by(CompatibilityHistory.created_at, CompatibilityHistory.id)
            )
        )
        for history in histories:
            history_by_run[history.research_run_id].append(history)

        oil_ids = {history.engine_oil_id for history in histories}
        oils_by_id = (
            {
                oil.id: oil
                for oil in self.db.scalars(
                    select(EngineOil)
                    .where(EngineOil.id.in_(oil_ids))
                    .order_by(EngineOil.id)
                )
            }
            if oil_ids
            else {}
        )

        timeline = []
        for run in runs:
            structured_result = run.structured_result or {}
            sources = structured_result.get("sources", [])
            if not isinstance(sources, list):
                sources = []
            run_histories = history_by_run[run.id]
            matched_oils = []
            seen_oil_ids = set()
            for history in run_histories:
                oil = oils_by_id.get(history.engine_oil_id)
                if oil is not None and oil.id not in seen_oil_ids:
                    seen_oil_ids.add(oil.id)
                    matched_oils.append(oil)
            timeline.append(
                ResearchTimelineEntry(
                    research_run=run,
                    sources=[source for source in sources if isinstance(source, dict)],
                    engine_specs=specs_by_run[run.id],
                    matched_oils=matched_oils,
                    compatibility_history=run_histories,
                )
            )
        return VehicleResearchHistory(vehicle=vehicle, timeline=timeline)
