from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import CompatibilityType, MatchMethod
from app.schemas.common import ORMModel


class CompatibilityCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vehicle_id: int
    engine_oil_id: int
    compatibility_type: CompatibilityType
    match_score: int = Field(ge=0, le=100)
    confidence_score: float = Field(ge=0, le=1)
    reason: str | None = Field(None, max_length=2000)


class CompatibilityRead(ORMModel, CompatibilityCreate):
    id: int
    research_run_id: int | None = None
    match_method: MatchMethod
    created_by: str
    created_at: datetime
