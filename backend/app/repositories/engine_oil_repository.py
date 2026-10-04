from __future__ import annotations

import re
import unicodedata

from sqlalchemy import select

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

    @staticmethod
    def _normalize_identity(value: str) -> str:
        value = unicodedata.normalize("NFKC", value).casefold()
        return re.sub(r"[^\w]+", "", value)

    @staticmethod
    def _normalize_sae(value: str) -> str:
        return re.sub(r"[^0-9W]", "", value.upper())

    def find_researched_product(
        self, brand: str, name: str, sae_viscosity: str, api_spec: str | None = None
    ) -> EngineOil | None:
        brand_key = self._normalize_identity(brand)
        name_key = self._normalize_identity(name)
        sae_key = self._normalize_sae(sae_viscosity)
        matches = [
            oil
            for oil in self.list_all()
            if self._normalize_identity(oil.brand) == brand_key
            and self._normalize_identity(oil.name) == name_key
            and self._normalize_sae(oil.sae_viscosity) == sae_key
        ]
        if not matches:
            return None
        if api_spec:
            api_key = self._normalize_identity(api_spec)
            exact_api = [
                oil
                for oil in matches
                if oil.api_spec and self._normalize_identity(oil.api_spec) == api_key
            ]
            if exact_api:
                return exact_api[0]
        return matches[0]
