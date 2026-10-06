import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.config import Settings
from app.models import Vehicle
from app.research.providers.openrouter.provider import (
    OpenRouterResearchProvider as ResearchAgent,
)
from app.research.providers.openrouter.provider import (
    ResearchExecutionError,
)


def response(content):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def valid_payload():
    return {
        "research_status": "FOUND",
        "vehicle_id": 1,
        "engine_code": "TU5",
        "recommended_sae": ["10W-40"],
        "confidence": 0.9,
        "sources": [],
    }


def vehicle():
    return Vehicle(
        id=1, manufacturer="Iran Khodro", model="Peugeot 206", engine_code="TU5"
    )


@pytest.mark.asyncio
async def test_research_uses_web_search_tool():
    client = SimpleNamespace(
        create_completion=AsyncMock(return_value=response(json.dumps(valid_payload())))
    )
    agent = ResearchAgent(client, Settings())
    await agent.research_vehicle_oil_spec(vehicle())
    assert client.create_completion.await_args.kwargs["tools"] == [
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


@pytest.mark.asyncio
async def test_one_repair_attempt_has_no_web_tool():
    client = SimpleNamespace(
        create_completion=AsyncMock(
            side_effect=[response("bad json"), response(json.dumps(valid_payload()))]
        )
    )
    result = await ResearchAgent(client, Settings()).research_vehicle_oil_spec(
        vehicle()
    )
    assert result.engine_code == "TU5"
    assert "tools" not in client.create_completion.await_args_list[1].kwargs


@pytest.mark.asyncio
async def test_invalid_repair_fails_safely():
    client = SimpleNamespace(
        create_completion=AsyncMock(
            side_effect=[response("bad"), response("still bad")]
        )
    )
    with pytest.raises(ResearchExecutionError, match="after one repair"):
        await ResearchAgent(client, Settings()).research_vehicle_oil_spec(vehicle())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"), [("vehicle_id", 999), ("engine_code", "WRONG")]
)
async def test_openrouter_requires_exact_vehicle_identity(field, value):
    payload = valid_payload()
    payload[field] = value
    client = SimpleNamespace(
        create_completion=AsyncMock(return_value=response(json.dumps(payload))),
        model="test/model",
    )
    with pytest.raises(ResearchExecutionError, match=field):
        await ResearchAgent(client, Settings()).research_vehicle_oil_spec(vehicle())


@pytest.mark.asyncio
async def test_openrouter_preserves_result_sources_as_grounding_metadata():
    payload = valid_payload()
    payload["sources"] = [
        {
            "title": "Owner manual",
            "url": "https://example.test/manual",
            "source_type": "OFFICIAL_MANUAL",
            "supported_claims": ["SAE 10W-40"],
        }
    ]
    client = SimpleNamespace(
        create_completion=AsyncMock(return_value=response(json.dumps(payload))),
        model="test/model",
    )
    execution = await ResearchAgent(client, Settings()).research_vehicle_oil_spec(
        vehicle()
    )
    assert execution.grounding_sources == [
        {"title": "Owner manual", "url": "https://example.test/manual"}
    ]
