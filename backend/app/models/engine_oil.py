from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin


class EngineOil(TimestampMixin, Base):
    __tablename__ = "engine_oils"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_from_research_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("research_runs.id", ondelete="RESTRICT"), index=True
    )
    brand: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    sae_viscosity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    api_spec: Mapped[str | None] = mapped_column(String(20), index=True)
    acea_spec: Mapped[str | None] = mapped_column(String(30), index=True)
    base_type: Mapped[str | None] = mapped_column(String(40))
    oem_approvals: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), default=list, nullable=False
    )
