from __future__ import annotations

from sqlalchemy import select

from app.domain.identity import engine_oil_identity_key
from app.models import EngineOil
from app.repositories.base import Repository


class EngineOilRepository(Repository[EngineOil]):
    model = EngineOil

    def list(self, sae_viscosity=None, api_spec=None, offset=0, limit=50):
        stmt = select(EngineOil)
        if sae_viscosity:
            stmt = stmt.where(EngineOil.sae_viscosity == sae_viscosity)
        if api_spec:
            stmt = stmt.where(EngineOil.api_spec == api_spec)
        return self.paged(stmt.order_by(EngineOil.id), offset, limit)

    def search_by_spec(self, sae_values: list[str]):
        return list(
            self.db.scalars(
                select(EngineOil).where(EngineOil.sae_viscosity.in_(sae_values))
            )
        )

    def list_all(self):
        return list(self.db.scalars(select(EngineOil).order_by(EngineOil.id)))

    def find_researched_product(
        self, brand: str, name: str, sae_viscosity: str, api_spec: str | None = None
    ) -> EngineOil | None:
        # API is deliberately not part of the stable business identity.
        return self.db.scalar(
            select(EngineOil).where(
                EngineOil.identity_key
                == engine_oil_identity_key(brand, name, sae_viscosity)
            )
        )
