from sqlalchemy import JSON, ForeignKey, String, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.identity import engine_oil_identity_key
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
    acea_specs: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), default=list, nullable=False
    )
    base_type: Mapped[str | None] = mapped_column(String(40))
    oem_approvals: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), default=list, nullable=False
    )
    identity_key: Mapped[str] = mapped_column(String(600), unique=True, nullable=False)


@event.listens_for(EngineOil, "before_insert")
@event.listens_for(EngineOil, "before_update")
def _set_engine_oil_identity(_mapper, _connection, oil: EngineOil) -> None:
    oil.identity_key = engine_oil_identity_key(oil.brand, oil.name, oil.sae_viscosity)
