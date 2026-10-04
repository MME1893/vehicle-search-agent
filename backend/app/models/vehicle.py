from sqlalchemy import Integer, String, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base
from app.models.common import TimestampMixin


class Vehicle(TimestampMixin, Base):
    __tablename__ = "vehicles"
    __table_args__ = (Index("ix_vehicles_manufacturer_model", "manufacturer", "model"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    manufacturer: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    trim: Mapped[str | None] = mapped_column(String(120))
    production_year_from: Mapped[int | None] = mapped_column(Integer)
    production_year_to: Mapped[int | None] = mapped_column(Integer)
    engine_code: Mapped[str | None] = mapped_column(String(80), index=True)
    engine_displacement: Mapped[str | None] = mapped_column(String(40))
    fuel_type: Mapped[str | None] = mapped_column(String(40))
