from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ResearchRun(Base):
    __tablename__ = "research_runs"
    __table_args__ = (
        CheckConstraint(
            "research_status IN ('FOUND','INSUFFICIENT')",
            name="ck_research_status",
        ),
        CheckConstraint(
            "evaluation_status IN ('ACCEPTED','NEEDS_REVIEW','REJECTED')",
            name="ck_research_evaluation_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str | None] = mapped_column(String(180))
    matching_strategy: Mapped[str] = mapped_column(String(50), nullable=False)
    research_status: Mapped[str] = mapped_column(String(30), nullable=False)
    evaluation_status: Mapped[str] = mapped_column(String(30), nullable=False)
    evaluation_reason: Mapped[str] = mapped_column(String(2000), nullable=False)
    raw_research_text: Mapped[str | None] = mapped_column(Text)
    structured_result: Mapped[dict | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )
    search_queries: Mapped[list] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), default=list, nullable=False
    )
    grounding_sources: Mapped[list] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), default=list, nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    stage1_duration_ms: Mapped[int | None] = mapped_column(Integer)
    stage2_duration_ms: Mapped[int | None] = mapped_column(Integer)
    total_duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
