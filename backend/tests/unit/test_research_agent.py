import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agents.research_agent import ResearchAgent, ResearchExecutionError
from app.core.config import Settings
from app.models import Vehicle


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
        {"type": "openrouter:web_search"}
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
