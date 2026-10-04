from sqlalchemy import JSON, CheckConstraint, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin


class EngineSpec(TimestampMixin, Base):
    __tablename__ = "engine_specs"
    __table_args__ = (
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_engine_specs_confidence"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    research_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("research_runs.id", ondelete="RESTRICT"), index=True
    )
    engine_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    recommended_sae: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), default=list, nullable=False
    )
    alternative_sae: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), default=list, nullable=False
    )
    minimum_api: Mapped[str | None] = mapped_column(String(20))
    acea_specs: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), default=list, nullable=False
    )
    oem_approvals: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), default=list, nullable=False
    )
    source: Mapped[str | None] = mapped_column(String(180))
    source_url: Mapped[str | None] = mapped_column(String(1000))
    evidence: Mapped[dict | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="PENDING", nullable=False)
