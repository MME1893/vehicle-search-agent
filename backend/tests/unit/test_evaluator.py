import pytest

from app.research.evaluator import evaluate_research
from app.research.schemas import EngineOilResearchResult


def result(*, sources=None, **overrides):
    value = {
        "research_status": "FOUND",
        "vehicle_id": 1,
        "engine_code": "TU5",
        "recommended_sae": ["10W-40"],
        "confidence": 0.9,
        "sources": sources or [],
    }
    value.update(overrides)
    return EngineOilResearchResult.model_validate(value)


def source(kind, domain="example.com"):
    return {
        "title": domain,
        "url": f"https://{domain}/oil",
        "source_type": kind,
        "supported_claims": ["SAE 10W-40"],
    }


@pytest.mark.parametrize("kind", ["OFFICIAL_MANUAL", "OFFICIAL_MANUFACTURER"])
def test_accepts_official_evidence(kind):
    assert evaluate_research(result(sources=[source(kind)]), 0.8).accepted


def test_accepts_two_independent_secondary_sources():
    sources = [
        source("LUBRICANT_MANUFACTURER", "iranol.ir"),
        source("SPECIALIZED_DATABASE", "amiranoil.ir"),
    ]
    assert evaluate_research(result(sources=sources), 0.8).accepted


def test_source_domain_identifies_redirected_sources_as_independent():
    redirect_url = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/x"
    sources = [
        {
            **source("LUBRICANT_MANUFACTURER", "iranol.ir"),
            "url": redirect_url,
            "domain": "www.iranol.ir",
        },
        {
            **source("SPECIALIZED_DATABASE", "amiranoil.ir"),
            "url": redirect_url,
            "domain": "amiranoil.ir",
        },
    ]
    assert evaluate_research(result(sources=sources), 0.8).accepted


def test_actual_sae_and_api_claim_values_are_recognized():
    researched = result(
        minimum_api="SL",
        sources=[
            {
                **source("OFFICIAL_MANUAL"),
                "supported_claims": ["SAE 10W-40", "API SL"],
            }
        ],
    )
    assert evaluate_research(researched, 0.8).accepted


def test_multiple_documented_sae_options_are_accepted():
    researched = result(
        recommended_sae=["10W-40", "5W-40"],
        alternative_sae=["5W-30"],
        sources=[
            {
                **source("OFFICIAL_MANUAL"),
                "supported_claims": ["SAE 10W-40", "SAE 5W-40", "SAE 5W-30"],
            }
        ],
        notes="5W-30 applies in colder weather",
    )
    assert evaluate_research(researched, 0.8).accepted


def test_secondary_sources_must_support_the_same_sae():
    first = source("LUBRICANT_MANUFACTURER", "iranol.ir")
    second = source("SPECIALIZED_DATABASE", "amiranoil.ir")
    first["supported_claims"] = ["SAE 5W-30"]
    second["supported_claims"] = ["SAE 10W-40"]
    evaluation = evaluate_research(
        result(sources=[first, second], recommended_sae=["5W-30", "10W-40"]), 0.8
    )
    assert evaluation.needs_review


@pytest.mark.parametrize(
    "case",
    [
        result(sources=[source("SPECIALIZED_DATABASE")]),
        result(sources=[source("LOW_QUALITY")]),
        result(sources=[source("OFFICIAL_MANUAL")], recommended_sae=[]),
        result(sources=[source("OFFICIAL_MANUAL")], confidence=0.5),
    ],
)
def test_uncertain_evidence_needs_review(case):
    evaluation = evaluate_research(case, 0.8)
    assert not evaluation.accepted and evaluation.needs_review
