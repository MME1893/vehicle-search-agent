import logging
import time

from app.models import Vehicle
from app.research.parser import ResearchResultParseError, parse_research_result
from app.research.prompts.opencode import build_opencode_vehicle_prompt
from app.research.providers.opencode.client import OpenCodeClient
from app.research.providers.openrouter.provider import ResearchExecutionError
from app.research.schemas import ResearchExecution

logger = logging.getLogger(__name__)


class OpenCodeResearchProvider:
    provider_name = "opencode"

    def __init__(self, client: OpenCodeClient):
        self.client = client

    async def aclose(self) -> None:
        await self.client.aclose()

    @staticmethod
    def build_vehicle_prompt(vehicle: Vehicle) -> str:
        return build_opencode_vehicle_prompt(vehicle)

    async def research_vehicle_oil_spec(
        self, vehicle: Vehicle
    ) -> ResearchExecution:
        logger.info("[OpenCode] Vehicle: %s", vehicle.id)
        raw = await self.client.run(
            self.build_vehicle_prompt(vehicle), vehicle_id=vehicle.id
        )
        logger.info("[OpenCode] Parsing result...")
        parsing_started = time.perf_counter()
        try:
            result = parse_research_result(raw)
        except ResearchResultParseError as exc:
            raise ResearchExecutionError(
                "OpenCode returned invalid research JSON."
            ) from exc
        logger.info(
            "[OpenCode] Pydantic parsing PASS in %.3fs",
            time.perf_counter() - parsing_started,
        )
        if result.vehicle_id != vehicle.id:
            raise ResearchExecutionError(
                "OpenCode returned a vehicle_id that does not match the requested vehicle."
            )
        if vehicle.engine_code and result.engine_code != vehicle.engine_code:
            raise ResearchExecutionError(
                "OpenCode returned an engine_code that does not exactly match the "
                "requested vehicle."
            )
        if len(result.sources) > 3:
            raise ResearchExecutionError(
                "OpenCode returned more than the allowed 3 research sources."
            )
        logger.info(
            "OpenCode web research completed status=%s sources=%s confidence=%.2f",
            result.research_status.value,
            len(result.sources),
            result.confidence,
        )
        return ResearchExecution(
            research=result,
            provider=self.provider_name,
            model=self.client.model,
            raw_research_text=raw,
            search_queries=list(getattr(self.client, "last_search_queries", [])),
            grounding_sources=[
                {"title": source.title, "url": source.url}
                for source in result.sources
            ],
        )
