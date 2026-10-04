from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class EngineOilCreate(BaseModel):
    brand: str = Field(min_length=1)
    name: str = Field(min_length=1)
    sae_viscosity: str = Field(pattern=r"^\d{1,2}W-\d{2}$")
    api_spec: str | None = None
    acea_spec: str | None = None
    base_type: str | None = None
    oem_approvals: list[str] = Field(default_factory=list)


class EngineOilUpdate(BaseModel):
    brand: str | None = Field(None, min_length=1)
    name: str | None = Field(None, min_length=1)
    sae_viscosity: str | None = Field(None, pattern=r"^\d{1,2}W-\d{2}$")
    api_spec: str | None = None
    acea_spec: str | None = None
    base_type: str | None = None
    oem_approvals: list[str] | None = None


class EngineOilRead(ORMModel, EngineOilCreate):
    id: int
    created_from_research_run_id: int | None = None
