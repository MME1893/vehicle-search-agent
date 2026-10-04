from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin


class Compatibility(TimestampMixin, Base):
    __tablename__ = "vehicle_engine_oil_compatibilities"
    __table_args__ = (
        UniqueConstraint("vehicle_id", "engine_oil_id", name="uq_vehicle_oil"),
        CheckConstraint(
            "match_score >= 0 AND match_score <= 100", name="ck_compatibility_score"
        ),
        CheckConstraint(
            "confidence_score >= 0 AND confidence_score <= 1",
            name="ck_compatibility_confidence",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    engine_oil_id: Mapped[int] = mapped_column(
        ForeignKey("engine_oils.id", ondelete="CASCADE"), nullable=False, index=True
    )
    research_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("research_runs.id", ondelete="RESTRICT"), index=True
    )
    engine_spec_id: Mapped[int | None] = mapped_column(
        ForeignKey("engine_specs.id", ondelete="RESTRICT"), index=True
    )
    compatibility_type: Mapped[str] = mapped_column(String(30), nullable=False)
    match_score: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(2000))
    created_by: Mapped[str] = mapped_column(
        String(30), default="SYSTEM", nullable=False
    )
    review_status: Mapped[str] = mapped_column(
        String(30), default="PENDING", nullable=False
    )
