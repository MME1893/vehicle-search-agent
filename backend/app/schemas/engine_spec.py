from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class EngineSpecCreate(BaseModel):
    engine_code: str = Field(min_length=1)
    recommended_sae: list[str] = Field(default_factory=list)
    alternative_sae: list[str] = Field(default_factory=list)
    minimum_api: str | None = None
    acea_specs: list[str] = Field(default_factory=list)
    oem_approvals: list[str] = Field(default_factory=list)
    source: str | None = None
    source_url: str | None = None
    evidence: dict | None = None
    confidence: float = Field(0, ge=0, le=1)
    status: str = "PENDING"


class EngineSpecRead(ORMModel, EngineSpecCreate):
    id: int
    research_run_id: int | None = None
