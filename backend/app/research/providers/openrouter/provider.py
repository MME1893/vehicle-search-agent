import json
import logging
from typing import Any

from pydantic import ValidationError

from app.core.config import Settings
from app.models import Vehicle
from app.research.errors import ResearchProviderError
from app.research.parser import ResearchResultParseError, parse_research_result
from app.research.prompts.openrouter import REPAIR_PROMPT, SYSTEM_PROMPT
from app.research.providers.openrouter.client import OpenRouterClient
from app.research.schemas import EngineOilResearchResult, ResearchExecution

logger = logging.getLogger(__name__)

_DIAGNOSTIC_LIMIT = 4000


def _truncate_diagnostic(value: str, limit: int = _DIAGNOSTIC_LIMIT) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _raw_preview(value: str, limit: int = _DIAGNOSTIC_LIMIT) -> str:
    return _truncate_diagnostic(repr(value), limit)


def _parse_failure_summary(exc: ResearchResultParseError) -> str:
    cause = exc.__cause__ or exc
    if isinstance(cause, json.JSONDecodeError):
        summary = (
            f"JSONDecodeError: {cause.msg} "
            f"line={cause.lineno} column={cause.colno}"
        )
    elif isinstance(cause, ValidationError):
        errors = []
        for error in cause.errors(
            include_url=False,
            include_context=False,
            include_input=False,
        ):
            location = ".".join(str(part) for part in error["loc"]) or "<root>"
            errors.append(f"{location}: {error['type']} — {error['msg']}")
        summary = "ValidationError: " + "; ".join(errors)
    else:
        summary = f"{type(cause).__name__}: {cause}"
    return _truncate_diagnostic(summary)


class ResearchExecutionError(ResearchProviderError):
    pass


class OpenRouterResearchProvider:
    provider_name = "openrouter"

    def __init__(self, client: OpenRouterClient, settings: Settings):
        self.client = client
        self.web_search_enabled = settings.research_web_search_enabled

    async def aclose(self) -> None:
        await self.client.aclose()

    @staticmethod
    def _validate_identity(vehicle: Vehicle, result) -> None:
        if result.vehicle_id != vehicle.id:
            raise ResearchExecutionError(
                "OpenRouter returned a vehicle_id that does not match the requested vehicle"
            )
        if vehicle.engine_code and result.engine_code != vehicle.engine_code:
            raise ResearchExecutionError(
                "OpenRouter returned an engine_code that does not exactly match the "
                "requested vehicle"
            )

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
            "engine_type": getattr(vehicle, "engine_type", None),
            "fuel_type": vehicle.fuel_type,
            "power_hp": getattr(vehicle, "power_hp", None),
            "torque_nm": getattr(vehicle, "torque_nm", None),
            "transmission": getattr(vehicle, "transmission", None),
            "drivetrain": getattr(vehicle, "drivetrain", None),
            "body_type": getattr(vehicle, "body_type", None),
            "body_style": getattr(vehicle, "body_style", None),
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

    async def research_vehicle_oil_spec(self, vehicle: Vehicle) -> ResearchExecution:
        logger.info("Research started vehicle_id=%s", vehicle.id)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": "Research this exact vehicle:\n"
                + json.dumps(self._vehicle_payload(vehicle), ensure_ascii=False),
            },
        ]
        tools = (
            [
                {
                    "type": "openrouter:web_search",
                    "parameters": {
                        "engine": "exa",
                        "max_results": 3,
                        "max_total_results": 3,
                        "max_uses": 1,
                    },
                }
            ]
            if self.web_search_enabled
            else None
        )
        response = await self.client.create_completion(messages=messages, tools=tools)
        raw = self._extract_content(response)
        try:
            result = parse_research_result(raw)
        except ResearchResultParseError as exc:
            failure_summary = _parse_failure_summary(exc)
            logger.warning(
                "OpenRouter initial research JSON invalid "
                "vehicle_id=%s model=%s reason=%s raw_preview=%s",
                vehicle.id,
                getattr(self.client, "model", None),
                failure_summary,
                _raw_preview(raw),
            )
            repair_schema = json.dumps(
                EngineOilResearchResult.model_json_schema(),
                ensure_ascii=False,
                separators=(",", ":"),
            )
            repair_system_message = (
                REPAIR_PROMPT
                + "\n\nThe previous response failed validation for this reason:\n"
                + failure_summary
                + "\n\nREQUIRED JSON SCHEMA:\n"
                + repair_schema
            )
            repair = await self.client.create_completion(
                messages=[
                    {"role": "system", "content": repair_system_message},
                    {
                        "role": "user",
                        "content": "INVALID RESPONSE TO REPAIR:\n\n" + raw,
                    },
                ]
            )
            repair_raw = self._extract_content(repair)
            try:
                result = parse_research_result(repair_raw)
            except ResearchResultParseError as exc:
                logger.error(
                    "OpenRouter repaired research JSON still invalid "
                    "vehicle_id=%s model=%s reason=%s raw_preview=%s",
                    vehicle.id,
                    getattr(self.client, "model", None),
                    _parse_failure_summary(exc),
                    _raw_preview(repair_raw),
                )
                raise ResearchExecutionError(
                    "OpenRouter returned invalid research JSON after one repair"
                ) from exc
        self._validate_identity(vehicle, result)
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
            grounding_sources=[
                {"title": source.title, "url": source.url} for source in result.sources
            ],
        )
