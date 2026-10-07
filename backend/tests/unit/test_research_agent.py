import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.config import Settings
from app.models import Vehicle
from app.research.prompts.openrouter import REPAIR_PROMPT
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
async def test_research_uses_web_search_tool(caplog):
    client = SimpleNamespace(
        create_completion=AsyncMock(return_value=response(json.dumps(valid_payload()))),
        model="test/model",
    )
    with caplog.at_level(logging.WARNING):
        execution = await ResearchAgent(client, Settings()).research_vehicle_oil_spec(
            vehicle()
        )
    assert execution.research.vehicle_id == 1
    assert client.create_completion.await_count == 1
    assert "OpenRouter initial research JSON invalid" not in caplog.text
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
async def test_one_repair_attempt_has_no_web_tool(caplog):
    invalid = '{"research_status":'
    client = SimpleNamespace(
        create_completion=AsyncMock(
            side_effect=[response(invalid), response(json.dumps(valid_payload()))]
        ),
        model="test/model",
    )
    with caplog.at_level(logging.WARNING):
        result = await ResearchAgent(client, Settings()).research_vehicle_oil_spec(
            vehicle()
        )
    assert result.engine_code == "TU5"
    repair_request = client.create_completion.await_args_list[1].kwargs
    assert "tools" not in repair_request
    repair_messages = repair_request["messages"]
    repair_system_message = repair_messages[0]["content"]
    assert REPAIR_PROMPT in repair_system_message
    assert "JSONDecodeError" in repair_system_message
    for field in (
        "research_status",
        "vehicle_id",
        "engine_code",
        "recommended_sae",
        "recommended_products",
        "sources",
        "confidence",
    ):
        assert f'"{field}"' in repair_system_message
    assert repair_messages[1]["content"] == (
        "INVALID RESPONSE TO REPAIR:\n\n" + invalid
    )
    assert "OpenRouter initial research JSON invalid" in caplog.text
    assert "vehicle_id=1" in caplog.text
    assert "model=test/model" in caplog.text
    assert "JSONDecodeError" in caplog.text
    assert "raw_preview=" in caplog.text
    assert repr(invalid) in caplog.text


@pytest.mark.asyncio
async def test_invalid_repair_fails_safely(caplog):
    client = SimpleNamespace(
        create_completion=AsyncMock(
            side_effect=[response("bad"), response("still bad")]
        ),
        model="test/model",
    )
    with caplog.at_level(logging.WARNING), pytest.raises(
        ResearchExecutionError,
        match="OpenRouter returned invalid research JSON after one repair",
    ):
        await ResearchAgent(client, Settings()).research_vehicle_oil_spec(vehicle())
    assert client.create_completion.await_count == 2
    error_messages = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.ERROR
    ]
    assert len(error_messages) == 1
    repaired_error = error_messages[0]
    assert "OpenRouter repaired research JSON still invalid" in repaired_error
    assert "vehicle_id=1" in repaired_error
    assert "model=test/model" in repaired_error
    assert "reason=JSONDecodeError" in repaired_error
    assert "raw_preview=" in repaired_error
    assert repr("still bad") in repaired_error


@pytest.mark.asyncio
async def test_schema_validation_failure_is_logged_before_repair(caplog):
    invalid_payload = valid_payload()
    invalid_payload["confidence"] = 2
    client = SimpleNamespace(
        create_completion=AsyncMock(
            side_effect=[
                response(json.dumps(invalid_payload)),
                response(json.dumps(valid_payload())),
            ]
        ),
        model="test/model",
    )

    with caplog.at_level(logging.WARNING):
        await ResearchAgent(client, Settings()).research_vehicle_oil_spec(vehicle())

    assert "OpenRouter initial research JSON invalid" in caplog.text
    assert "ValidationError" in caplog.text
    assert "confidence" in caplog.text
    assert "less_than_equal" in caplog.text


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
