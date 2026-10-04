from pydantic import BaseModel, Field
from app.schemas.common import ORMModel


class VehicleCreate(BaseModel):
    manufacturer: str = Field(min_length=1, max_length=120)
    model: str = Field(min_length=1, max_length=120)
    trim: str | None = None
    production_year_from: int | None = Field(None, ge=1886, le=3000)
    production_year_to: int | None = Field(None, ge=1886, le=3000)
    engine_code: str | None = None
    engine_displacement: str | None = None
    fuel_type: str | None = None


class VehicleUpdate(BaseModel):
    manufacturer: str | None = Field(None, min_length=1)
    model: str | None = Field(None, min_length=1)
    trim: str | None = None
    production_year_from: int | None = Field(None, ge=1886, le=3000)
    production_year_to: int | None = Field(None, ge=1886, le=3000)
    engine_code: str | None = None
    engine_displacement: str | None = None
    fuel_type: str | None = None


class VehicleRead(ORMModel, VehicleCreate):
    id: int
