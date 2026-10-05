from collections import defaultdict

from sqlalchemy import select

from app.models import Compatibility, EngineOil, ResearchRun
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
        compatibility_by_run = defaultdict(list)
        compatibilities = list(
            self.db.scalars(
                select(Compatibility)
                .where(
                    Compatibility.vehicle_id == vehicle_id,
                    Compatibility.research_run_id.in_(run_ids),
                )
                .order_by(Compatibility.created_at, Compatibility.id)
            )
        )
        for compatibility in compatibilities:
            compatibility_by_run[compatibility.research_run_id].append(compatibility)

        oil_ids = {item.engine_oil_id for item in compatibilities}
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
            run_compatibilities = compatibility_by_run[run.id]
            matched_oils = []
            seen_oil_ids = set()
            for compatibility in run_compatibilities:
                oil = oils_by_id.get(compatibility.engine_oil_id)
                if oil is not None and oil.id not in seen_oil_ids:
                    seen_oil_ids.add(oil.id)
                    matched_oils.append(oil)
            timeline.append(
                ResearchTimelineEntry(
                    research_run=run,
                    sources=[source for source in sources if isinstance(source, dict)],
                    matched_oils=matched_oils,
                    compatibilities=run_compatibilities,
                )
            )
        return VehicleResearchHistory(vehicle=vehicle, timeline=timeline)
