from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    desc,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import CreatedAtMixin


class Compatibility(CreatedAtMixin, Base):
    __tablename__ = "vehicle_engine_oil_compatibilities"
    __table_args__ = (
        Index("ix_compatibility_created_at", "created_at"),
        Index("ix_compat_vehicle", "vehicle_id"),
        Index("ix_compat_oil", "engine_oil_id"),
        Index(
            "ix_compatibility_pair_latest",
            "vehicle_id",
            "engine_oil_id",
            desc("created_at"),
            desc("id"),
        ),
        UniqueConstraint(
            "vehicle_id",
            "engine_oil_id",
            "research_run_id",
            name="uq_compatibility_research_run_oil",
        ),
        CheckConstraint(
            "match_score >= 0 AND match_score <= 100", name="ck_compatibility_score"
        ),
        CheckConstraint(
            "confidence_score >= 0 AND confidence_score <= 1",
            name="ck_compatibility_confidence",
        ),
        CheckConstraint(
            "match_method IN ('MANUAL','DIRECT_RESEARCH_PRODUCT',"
            "'DETERMINISTIC_SPEC_MATCH','PROVIDER_CATALOG_MATCH')",
            name="ck_compatibility_match_method",
        ),
        CheckConstraint(
            "compatibility_type IN ('RECOMMENDED','COMPATIBLE','CONDITIONAL')",
            name="ck_compatibility_type",
        ),
        CheckConstraint(
            "created_by IN ('SYSTEM','AGENT','ADMIN')",
            name="ck_compatibility_created_by",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="RESTRICT"), nullable=False
    )
    engine_oil_id: Mapped[int] = mapped_column(
        ForeignKey("engine_oils.id", ondelete="RESTRICT"), nullable=False
    )
    research_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("research_runs.id", ondelete="RESTRICT"), index=True
    )
    match_method: Mapped[str] = mapped_column(String(50), nullable=False)
    compatibility_type: Mapped[str] = mapped_column(String(30), nullable=False)
    match_score: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(2000))
    created_by: Mapped[str] = mapped_column(
        String(30), default="SYSTEM", nullable=False
    )
