from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class EngineOilCreate(BaseModel):
    brand: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=180)
    sae_viscosity: str = Field(max_length=20, pattern=r"^\d{1,2}W-\d{2}$")
    api_spec: str | None = Field(None, max_length=20)
    acea_specs: list[str] = Field(default_factory=list)
    base_type: str | None = Field(None, max_length=40)
    oem_approvals: list[str] = Field(default_factory=list)


class EngineOilUpdate(BaseModel):
    brand: str = Field(None, min_length=1, max_length=120)
    name: str = Field(None, min_length=1, max_length=180)
    sae_viscosity: str = Field(None, max_length=20, pattern=r"^\d{1,2}W-\d{2}$")
    api_spec: str | None = Field(None, max_length=20)
    acea_specs: list[str] | None = None
    base_type: str | None = Field(None, max_length=40)
    oem_approvals: list[str] | None = None


class EngineOilRead(ORMModel, EngineOilCreate):
    id: int
    created_from_research_run_id: int | None = None
