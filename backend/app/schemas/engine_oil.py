from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class EngineOilCreate(BaseModel):
    brand: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=180)
    sae_viscosity: str = Field(max_length=20, pattern=r"^\d{1,2}W-\d{2}$")
    api_spec: str | None = Field(None, max_length=20)
    acea_specs: list[str] = Field(default_factory=list)
    ilsac_spec: str | None = Field(None, max_length=20)
    base_type: str | None = Field(None, max_length=40)
    oem_approvals: list[str] = Field(default_factory=list)
    package_volume_liters: Decimal | None = Field(None, gt=0, max_digits=6, decimal_places=2)
    package_volume_label: str | None = Field(None, max_length=40)
    claimed_service_interval_km: int | None = Field(None, gt=0)


class EngineOilUpdate(BaseModel):
    brand: str = Field(None, min_length=1, max_length=120)
    name: str = Field(None, min_length=1, max_length=180)
    sae_viscosity: str = Field(None, max_length=20, pattern=r"^\d{1,2}W-\d{2}$")
    api_spec: str | None = Field(None, max_length=20)
    acea_specs: list[str] | None = None
    ilsac_spec: str | None = Field(None, max_length=20)
    base_type: str | None = Field(None, max_length=40)
    oem_approvals: list[str] | None = None
    package_volume_liters: Decimal | None = Field(None, gt=0, max_digits=6, decimal_places=2)
    package_volume_label: str | None = Field(None, max_length=40)
    claimed_service_interval_km: int | None = Field(None, gt=0)


class EngineOilRead(ORMModel, EngineOilCreate):
    id: int
    created_from_research_run_id: int | None = None
