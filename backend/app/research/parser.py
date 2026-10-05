import json

from pydantic import ValidationError

from app.research.schemas import CatalogResearchResult, EngineOilResearchResult


class ResearchResultParseError(ValueError):
    pass


def _strip_code_fence(content: str) -> str:
    value = content.strip()
    if not value.startswith("```"):
        return value
    lines = value.splitlines()
    if lines and lines[0].strip().lower() in {"```", "```json"}:
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def parse_research_result(raw_content: str) -> EngineOilResearchResult:
    try:
        payload = json.loads(_strip_code_fence(raw_content))
        return EngineOilResearchResult.model_validate(payload)
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise ResearchResultParseError(
            "research result is not valid schema JSON"
        ) from exc


def parse_catalog_research_result(raw_content: str) -> CatalogResearchResult:
    try:
        payload = json.loads(_strip_code_fence(raw_content))
        return CatalogResearchResult.model_validate(payload)
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise ResearchResultParseError(
            "catalog research result is not valid schema JSON"
        ) from exc
