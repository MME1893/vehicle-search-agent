from typing import Protocol, runtime_checkable

from app.models import EngineOil, Vehicle
from app.research.schemas import ResearchExecution


@runtime_checkable
class ResearchProvider(Protocol):
    provider_name: str

    async def aclose(self) -> None: ...

    async def research_vehicle_oil_spec(
        self,
        vehicle: Vehicle,
    ) -> ResearchExecution: ...


@runtime_checkable
class CatalogResearchProvider(ResearchProvider, Protocol):
    async def research_vehicle_with_catalog(
        self,
        vehicle: Vehicle,
        oils: list[EngineOil],
    ) -> ResearchExecution: ...
