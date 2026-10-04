import pytest

from app.agents.parser import ResearchResultParseError, parse_research_result


def payload(**overrides):
    value = {
        "research_status": "FOUND",
        "vehicle_id": 1,
        "engine_code": "TU5",
        "recommended_sae": ["10W-40"],
        "alternative_sae": [],
        "minimum_api": None,
        "acea_specs": [],
        "oem_approvals": [],
        "confidence": 0.9,
        "sources": [],
        "recommended_products": [],
        "notes": None,
    }
    value.update(overrides)
    return value


def test_parses_valid_json_and_nullable_optional_fields():
    import json

    result = parse_research_result(json.dumps(payload()))
    assert result.minimum_api is None
    assert result.acea_specs == []
    assert result.oem_approvals == []
    assert result.sources == []


def test_strips_json_code_fence():
    import json

    result = parse_research_result(f"```json\n{json.dumps(payload())}\n```")
    assert result.engine_code == "TU5"


@pytest.mark.parametrize(
    "raw",
    [
        "not-json",
        '{"research_status":"FOUND"}',
        '{"research_status":"FOUND","vehicle_id":1,"confidence":2}',
    ],
)
def test_rejects_malformed_or_invalid_results(raw):
    with pytest.raises(ResearchResultParseError):
        parse_research_result(raw)
