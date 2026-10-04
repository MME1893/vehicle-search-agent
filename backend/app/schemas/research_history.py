from datetime import datetime
from typing import Any

from app.schemas.common import ORMModel
from app.schemas.engine_oil import EngineOilRead
from app.schemas.engine_spec import EngineSpecRead
from app.schemas.vehicle import VehicleRead


class ResearchRunRead(ORMModel):
    id: int
    vehicle_id: int
    provider: str
    model: str | None
    matching_strategy: str
    status: str
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


class CompatibilityHistoryRead(ORMModel):
    id: int
    compatibility_id: int
    vehicle_id: int
    engine_oil_id: int
    research_run_id: int
    engine_spec_id: int
    match_method: str
    compatibility_type: str
    match_score: int
    confidence_score: float
    reason: str | None
    created_at: datetime


class ResearchTimelineEntry(ORMModel):
    research_run: ResearchRunRead
    sources: list[dict[str, Any]]
    engine_specs: list[EngineSpecRead]
    matched_oils: list[EngineOilRead]
    compatibility_history: list[CompatibilityHistoryRead]


class VehicleResearchHistory(ORMModel):
    vehicle: VehicleRead
    timeline: list[ResearchTimelineEntry]
