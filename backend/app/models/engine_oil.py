from decimal import Decimal

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Integer,
    Numeric,
    String,
    event,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.identity import engine_oil_identity_key
from app.models.common import TimestampMixin


class EngineOil(TimestampMixin, Base):
    __tablename__ = "engine_oils"
    __table_args__ = (
        CheckConstraint(
            "package_volume_liters IS NULL OR package_volume_liters > 0",
            name="ck_engine_oils_package_volume_liters_positive",
        ),
        CheckConstraint(
            "claimed_service_interval_km IS NULL OR claimed_service_interval_km > 0",
            name="ck_engine_oils_claimed_service_interval_km_positive",
        ),
    )
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
    ilsac_spec: Mapped[str | None] = mapped_column(String(20), index=True)
    base_type: Mapped[str | None] = mapped_column(String(40))
    oem_approvals: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), default=list, nullable=False
    )
    package_volume_liters: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    package_volume_label: Mapped[str | None] = mapped_column(String(40))
    claimed_service_interval_km: Mapped[int | None] = mapped_column(Integer)
    identity_key: Mapped[str] = mapped_column(String(600), unique=True, nullable=False)


@event.listens_for(EngineOil, "before_insert")
@event.listens_for(EngineOil, "before_update")
def _set_engine_oil_identity(_mapper, _connection, oil: EngineOil) -> None:
    oil.identity_key = engine_oil_identity_key(
        oil.brand, oil.name, oil.sae_viscosity, oil.package_volume_liters
    )
