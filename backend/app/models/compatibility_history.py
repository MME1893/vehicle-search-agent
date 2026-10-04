from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CompatibilityHistory(Base):
    __tablename__ = "compatibility_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    compatibility_id: Mapped[int] = mapped_column(
        ForeignKey("vehicle_engine_oil_compatibilities.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    engine_oil_id: Mapped[int] = mapped_column(
        ForeignKey("engine_oils.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    research_run_id: Mapped[int] = mapped_column(
        ForeignKey("research_runs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    engine_spec_id: Mapped[int] = mapped_column(
        ForeignKey("engine_specs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    match_method: Mapped[str] = mapped_column(String(50), nullable=False)
    compatibility_type: Mapped[str] = mapped_column(String(30), nullable=False)
    match_score: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
