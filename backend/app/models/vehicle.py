from sqlalchemy import CheckConstraint, Index, Integer, String, event
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.identity import vehicle_identity_key
from app.models.common import TimestampMixin


class Vehicle(TimestampMixin, Base):
    __tablename__ = "vehicles"
    __table_args__ = (
        Index("ix_vehicles_manufacturer_model", "manufacturer", "model"),
        CheckConstraint(
            "production_year_from IS NULL OR production_year_to IS NULL "
            "OR production_year_from <= production_year_to",
            name="ck_vehicles_production_year_range",
        ),
        CheckConstraint(
            "power_hp IS NULL OR power_hp > 0",
            name="ck_vehicles_power_hp_positive",
        ),
        CheckConstraint(
            "torque_nm IS NULL OR torque_nm > 0",
            name="ck_vehicles_torque_nm_positive",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    manufacturer: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    trim: Mapped[str | None] = mapped_column(String(120))
    production_year_from: Mapped[int | None] = mapped_column(Integer)
    production_year_to: Mapped[int | None] = mapped_column(Integer)
    engine_code: Mapped[str | None] = mapped_column(String(80), index=True)
    engine_displacement: Mapped[str | None] = mapped_column(String(40))
    engine_type: Mapped[str | None] = mapped_column(String(80))
    fuel_type: Mapped[str | None] = mapped_column(String(40))
    power_hp: Mapped[int | None] = mapped_column(Integer)
    torque_nm: Mapped[int | None] = mapped_column(Integer)
    transmission: Mapped[str | None] = mapped_column(String(80))
    drivetrain: Mapped[str | None] = mapped_column(String(40))
    body_type: Mapped[str | None] = mapped_column(String(40))
    body_style: Mapped[str | None] = mapped_column(String(80))
    identity_key: Mapped[str] = mapped_column(String(600), unique=True, nullable=False)


@event.listens_for(Vehicle, "before_insert")
@event.listens_for(Vehicle, "before_update")
def _set_vehicle_identity(_mapper, _connection, vehicle: Vehicle) -> None:
    vehicle.identity_key = vehicle_identity_key(
        vehicle.manufacturer,
        vehicle.model,
        vehicle.trim,
        vehicle.production_year_from,
        vehicle.production_year_to,
        vehicle.engine_code,
        vehicle.engine_displacement,
        vehicle.engine_type,
        vehicle.fuel_type,
        vehicle.transmission,
        vehicle.drivetrain,
        vehicle.body_type,
        vehicle.body_style,
    )
