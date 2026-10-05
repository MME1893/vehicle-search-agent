from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class VehicleCreate(BaseModel):
    manufacturer: str = Field(min_length=1, max_length=120)
    model: str = Field(min_length=1, max_length=120)
    trim: str | None = Field(None, max_length=120)
    production_year_from: int | None = Field(None, ge=1886, le=3000)
    production_year_to: int | None = Field(None, ge=1886, le=3000)
    engine_code: str | None = Field(None, max_length=80)
    engine_displacement: str | None = Field(None, max_length=40)
    engine_type: str | None = Field(None, max_length=80)
    fuel_type: str | None = Field(None, max_length=40)
    power_hp: int | None = Field(None, gt=0)
    torque_nm: int | None = Field(None, gt=0)
    transmission: str | None = Field(None, max_length=80)
    drivetrain: str | None = Field(None, max_length=40)
    body_type: str | None = Field(None, max_length=40)
    body_style: str | None = Field(None, max_length=80)


class VehicleUpdate(BaseModel):
    manufacturer: str = Field(None, min_length=1, max_length=120)
    model: str = Field(None, min_length=1, max_length=120)
    trim: str | None = Field(None, max_length=120)
    production_year_from: int | None = Field(None, ge=1886, le=3000)
    production_year_to: int | None = Field(None, ge=1886, le=3000)
    engine_code: str | None = Field(None, max_length=80)
    engine_displacement: str | None = Field(None, max_length=40)
    engine_type: str | None = Field(None, max_length=80)
    fuel_type: str | None = Field(None, max_length=40)
    power_hp: int | None = Field(None, gt=0)
    torque_nm: int | None = Field(None, gt=0)
    transmission: str | None = Field(None, max_length=80)
    drivetrain: str | None = Field(None, max_length=40)
    body_type: str | None = Field(None, max_length=40)
    body_style: str | None = Field(None, max_length=80)


class VehicleRead(ORMModel, VehicleCreate):
    id: int
