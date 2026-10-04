from typing import Protocol, runtime_checkable

from app.agents.schemas import CatalogResearchResult, EngineOilResearchResult
from app.models import EngineOil, Vehicle


@runtime_checkable
class ResearchProvider(Protocol):
    provider_name: str

    async def research_vehicle_oil_spec(
        self,
        vehicle: Vehicle,
    ) -> EngineOilResearchResult: ...


@runtime_checkable
class CatalogResearchProvider(ResearchProvider, Protocol):
    async def research_vehicle_with_catalog(
        self,
        vehicle: Vehicle,
        oils: list[EngineOil],
    ) -> CatalogResearchResult: ...
