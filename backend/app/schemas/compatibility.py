from pydantic import BaseModel, Field, field_validator

from app.core.constants import COMPATIBILITY_TYPES, CREATED_BY
from app.schemas.common import ORMModel


class CompatibilityCreate(BaseModel):
    vehicle_id: int
    engine_oil_id: int
    compatibility_type: str
    match_score: int = Field(ge=0, le=100)
    confidence_score: float = Field(ge=0, le=1)
    reason: str | None = None
    created_by: str = "SYSTEM"
    review_status: str = "PENDING"

    @field_validator("compatibility_type")
    @classmethod
    def valid_type(cls, v: str) -> str:
        if v not in COMPATIBILITY_TYPES:
            raise ValueError("invalid compatibility type")
        return v

    @field_validator("created_by")
    @classmethod
    def valid_creator(cls, v: str) -> str:
        if v not in CREATED_BY:
            raise ValueError("invalid created_by")
        return v


class CompatibilityRead(ORMModel, CompatibilityCreate):
    id: int
    research_run_id: int | None = None
    engine_spec_id: int | None = None
