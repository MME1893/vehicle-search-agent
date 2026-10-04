import json
import logging
from typing import Any

from app.agents.client import OpenRouterClient
from app.agents.errors import ResearchProviderError
from app.agents.parser import ResearchResultParseError, parse_research_result
from app.agents.prompts import REPAIR_PROMPT, SYSTEM_PROMPT
from app.agents.schemas import ResearchExecution
from app.core.config import Settings
from app.models import Vehicle

logger = logging.getLogger(__name__)


class ResearchExecutionError(ResearchProviderError):
    pass


class ResearchAgent:
    provider_name = "openrouter"

    def __init__(self, client: OpenRouterClient, settings: Settings):
        self.client = client
        self.web_search_enabled = settings.research_web_search_enabled

    @staticmethod
    def _vehicle_payload(vehicle: Vehicle) -> dict[str, Any]:
        return {
            "vehicle_id": vehicle.id,
            "manufacturer": vehicle.manufacturer,
            "model": vehicle.model,
            "trim": vehicle.trim,
            "production_year_from": vehicle.production_year_from,
            "production_year_to": vehicle.production_year_to,
            "engine_code": vehicle.engine_code,
            "engine_displacement": vehicle.engine_displacement,
            "fuel_type": vehicle.fuel_type,
        }

    @staticmethod
    def _extract_content(response: Any) -> str:
        choices = getattr(response, "choices", None)
        if not choices:
            raise ResearchExecutionError("OpenRouter returned no completion choices")
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None) if message else None
        if not isinstance(content, str) or not content.strip():
            raise ResearchExecutionError("OpenRouter returned empty assistant content")
        return content.strip()

    async def research_vehicle_oil_spec(
        self, vehicle: Vehicle
    ) -> ResearchExecution:
        logger.info("Research started vehicle_id=%s", vehicle.id)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": "Research this exact vehicle:\n"
                + json.dumps(self._vehicle_payload(vehicle), ensure_ascii=False),
            },
        ]
        tools = [{"type": "openrouter:web_search"}] if self.web_search_enabled else None
        response = await self.client.create_completion(messages=messages, tools=tools)
        raw = self._extract_content(response)
        try:
            result = parse_research_result(raw)
        except ResearchResultParseError:
            repair = await self.client.create_completion(
                messages=[
                    {"role": "system", "content": REPAIR_PROMPT},
                    {"role": "user", "content": raw},
                ]
            )
            try:
                result = parse_research_result(self._extract_content(repair))
            except ResearchResultParseError as exc:
                raise ResearchExecutionError(
                    "OpenRouter returned invalid research JSON after one repair"
                ) from exc
        logger.info(
            "Web research completed status=%s sources=%s confidence=%.2f",
            result.research_status.value,
            len(result.sources),
            result.confidence,
        )
        return ResearchExecution(
            research=result,
            provider=self.provider_name,
            model=getattr(self.client, "model", None),
            raw_research_text=raw,
        )
