import logging

from app.agents.errors import GeminiProviderError
from app.agents.gemini_client import GeminiClient
from app.agents.parser import (
    ResearchResultParseError,
    parse_catalog_research_result,
    parse_research_result,
)
from app.agents.prompts import (
    build_catalog_extraction_prompt,
    build_catalog_research_prompt,
    build_vehicle_extraction_prompt,
    build_vehicle_research_prompt,
)
from app.agents.schemas import (
    CatalogResearchResult,
    EngineOilResearchResult,
    ResearchExecution,
)
from app.models import EngineOil, Vehicle

logger = logging.getLogger(__name__)


class GeminiResearchAdapter:
    provider_name = "gemini"

    def __init__(self, client: GeminiClient):
        self.client = client

    @staticmethod
    def _validate_identity(vehicle: Vehicle, result: EngineOilResearchResult) -> None:
        if result.vehicle_id != vehicle.id:
            raise GeminiProviderError(
                "Gemini returned a vehicle_id that does not match the requested vehicle"
            )
        if result.engine_code != vehicle.engine_code:
            raise GeminiProviderError(
                "Gemini returned an engine_code that does not exactly match the "
                "requested vehicle"
            )

    def _validate_grounding(self) -> None:
        if not self.client.last_grounding.is_grounded:
            raise GeminiProviderError(
                "Gemini returned no Google Search grounding metadata"
            )

    @staticmethod
    def _parse_structured(raw: str, *, catalog: bool = False):
        parser = parse_catalog_research_result if catalog else parse_research_result
        try:
            return parser(raw)
        except ResearchResultParseError as exc:
            raise GeminiProviderError(
                "Gemini returned invalid structured extraction JSON"
            ) from exc

    def _grounding_sources(self) -> list[dict[str, str | None]]:
        return [
            {"title": source.title, "url": source.uri}
            for source in self.client.last_grounding.sources
        ]

    async def research_vehicle_oil_spec(
        self, vehicle: Vehicle
    ) -> ResearchExecution:
        async with self.client.research_budget():
            response = await self.client.generate_grounded(
                build_vehicle_research_prompt(vehicle)
            )
            research_text = self.client.response_text(response)
            self._validate_grounding()
            raw = await self.client.generate_structured(
                build_vehicle_extraction_prompt(
                    vehicle, research_text, self._grounding_sources()
                ),
                EngineOilResearchResult,
            )
            result = self._parse_structured(raw)
            self._validate_identity(vehicle, result)
            return self._execution(result)

    async def research_vehicle_with_catalog(
        self, vehicle: Vehicle, oils: list[EngineOil]
    ) -> ResearchExecution:
        async with self.client.research_budget():
            response = await self.client.generate_grounded(
                build_catalog_research_prompt(vehicle, oils)
            )
            research_text = self.client.response_text(response)
            self._validate_grounding()
            raw = await self.client.generate_structured(
                build_catalog_extraction_prompt(
                    vehicle, research_text, self._grounding_sources(), oils
                ),
                CatalogResearchResult,
            )
            result = self._parse_structured(raw, catalog=True)
            self._validate_identity(vehicle, result.research)
            available_ids = {oil.id for oil in oils}
            returned_ids = [match.engine_oil_id for match in result.matches]
            unknown_ids = set(returned_ids) - available_ids
            if unknown_ids:
                raise GeminiProviderError(
                    "Gemini returned unknown engine_oil_id values: "
                    f"{sorted(unknown_ids)}"
                )
            if len(returned_ids) != len(set(returned_ids)):
                raise GeminiProviderError(
                    "Gemini returned duplicate engine_oil_id values"
                )
            return self._execution(result.research, result.matches)

    def _execution(self, research, matches=None) -> ResearchExecution:
        grounding = self.client.last_grounding
        return ResearchExecution(
            research=research,
            matches=list(matches or []),
            provider=self.provider_name,
            model=self.client.model,
            raw_research_text=self.client.last_research_text,
            search_queries=list(grounding.queries),
            grounding_sources=[
                {"title": source.title, "url": source.uri}
                for source in grounding.sources
            ],
            stage1_duration_ms=(
                round(self.client.last_grounded_duration * 1000)
                if self.client.last_grounded_duration is not None
                else None
            ),
            stage2_duration_ms=(
                round(self.client.last_extraction_duration * 1000)
                if self.client.last_extraction_duration is not None
                else None
            ),
        )
