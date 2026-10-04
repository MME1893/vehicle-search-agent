from pydantic import BaseModel, Field

from app.domain.enums import CompatibilityType, CreatedBy, MatchMethod
from app.schemas.common import ORMModel


class CompatibilityCreate(BaseModel):
    vehicle_id: int
    engine_oil_id: int
    compatibility_type: CompatibilityType
    match_score: int = Field(ge=0, le=100)
    confidence_score: float = Field(ge=0, le=1)
    reason: str | None = None
    created_by: CreatedBy = CreatedBy.SYSTEM


class CompatibilityRead(ORMModel, CompatibilityCreate):
    id: int
    research_run_id: int | None = None
    match_method: MatchMethod
