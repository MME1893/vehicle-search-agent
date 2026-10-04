from datetime import datetime
from typing import Any

from app.schemas.common import ORMModel
from app.schemas.compatibility import CompatibilityRead
from app.schemas.engine_oil import EngineOilRead
from app.schemas.vehicle import VehicleRead


class ResearchRunRead(ORMModel):
    id: int
    vehicle_id: int
    provider: str
    model: str | None
    matching_strategy: str
    research_status: str
    evaluation_status: str
    evaluation_reason: str
    raw_research_text: str | None
    structured_result: dict[str, Any] | None
    search_queries: list[Any]
    grounding_sources: list[Any]
    started_at: datetime
    completed_at: datetime
    stage1_duration_ms: int | None
    stage2_duration_ms: int | None
    total_duration_ms: int
    created_at: datetime


class ResearchTimelineEntry(ORMModel):
    research_run: ResearchRunRead
    sources: list[dict[str, Any]]
    matched_oils: list[EngineOilRead]
    compatibilities: list[CompatibilityRead]


class VehicleResearchHistory(ORMModel):
    vehicle: VehicleRead
    timeline: list[ResearchTimelineEntry]
