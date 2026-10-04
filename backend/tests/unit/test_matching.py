import pytest

from app.domain.oil_requirement import OilRequirement
from app.models import EngineOil
from app.services.matching.matcher import DeterministicMatcher
from app.services.matching.rules import (
    api_satisfies,
    extract_gasoline_api_categories,
    normalize_api_spec,
)


def test_recommended_match_and_cap():
    spec = OilRequirement(
        engine_code="TU5",
        recommended_sae=["5W-40"],
        alternative_sae=[],
        minimum_api="SL",
        acea_specs=["A3/B4"],
        oem_approvals=["VW 502 00"],
        confidence=0.9,
    )
    oil = EngineOil(
        brand="B",
        name="N",
        sae_viscosity="5W-40",
        api_spec="SP",
        acea_specs=["A3/B4"],
        oem_approvals=["VW 502 00"],
    )
    candidate = DeterministicMatcher().score(spec, oil)
    assert candidate.score == 100 and "recommended SAE" in candidate.reasons


def test_alternative_and_invalid_sae():
    spec = OilRequirement(
        engine_code="E",
        recommended_sae=[],
        alternative_sae=["10W-40"],
        minimum_api=None,
        acea_specs=[],
        oem_approvals=[],
        confidence=0,
    )
    matcher = DeterministicMatcher()
    assert (
        matcher.score(
            spec,
            EngineOil(brand="b", name="n", sae_viscosity="10W-40", oem_approvals=[]),
        ).score
        == 35
    )
    assert (
        matcher.score(
            spec,
            EngineOil(brand="b", name="n", sae_viscosity="5W-30", oem_approvals=[]),
        )
        is None
    )


def test_api_is_ranked_not_alphabetic():
    assert api_satisfies("SP", "SN") and not api_satisfies("SL", "SN")


@pytest.mark.parametrize(
    "value",
    ["API SL", "API-SL", "API: SL", "Minimum API: SL"],
)
def test_normalizes_api_spec_prefixes(value):
    assert normalize_api_spec(value) == "SL"


def test_extracts_only_gasoline_api_categories_from_compound_values():
    assert extract_gasoline_api_categories("SN") == ["SN"]
    assert extract_gasoline_api_categories("SN/CF") == ["SN"]
    assert extract_gasoline_api_categories("SL/CF") == ["SL"]
    assert extract_gasoline_api_categories("SN Plus") == ["SN PLUS"]
    assert extract_gasoline_api_categories("SQ/SP") == ["SQ", "SP"]
    assert extract_gasoline_api_categories("SQ/SP/SN Plus/SN") == [
        "SQ",
        "SP",
        "SN PLUS",
        "SN",
    ]


@pytest.mark.parametrize(
    ("actual", "minimum", "expected"),
    [
        ("SN/CF", "SL", True),
        ("SL/CF", "SN", False),
        ("SN Plus", "SN", True),
        ("SP", "SN Plus", True),
        ("SQ/SP/SN Plus/SN", "SP", True),
        ("SN", "SP", False),
    ],
)
def test_compound_api_satisfaction(actual, minimum, expected):
    assert api_satisfies(actual, minimum) is expected


def test_minimum_api_is_a_hard_requirement():
    spec = OilRequirement(
        engine_code="TU5",
        recommended_sae=["5W-40"],
        alternative_sae=[],
        minimum_api="SN",
        acea_specs=[],
        oem_approvals=[],
        confidence=0.9,
    )
    matcher = DeterministicMatcher()
    insufficient = EngineOil(
        brand="B",
        name="Insufficient",
        sae_viscosity="5W-40",
        api_spec="SL/CF",
        oem_approvals=[],
    )
    sufficient = EngineOil(
        brand="B",
        name="Sufficient",
        sae_viscosity="5W-40",
        api_spec="SN/CF",
        oem_approvals=[],
    )

    assert matcher.score(spec, insufficient) is None
    assert matcher.score(spec, sufficient) is not None


@pytest.mark.parametrize("minimum_api", ["API SL", "API: SL"])
def test_formatted_minimum_api_matches_higher_ranked_oil(minimum_api):
    spec = OilRequirement(
        engine_code="TU5",
        recommended_sae=["5W-40"],
        alternative_sae=[],
        minimum_api=minimum_api,
        acea_specs=[],
        oem_approvals=[],
        confidence=0.9,
    )
    oil = EngineOil(
        brand="B",
        name="Higher API",
        sae_viscosity="5W-40",
        api_spec="SN",
        oem_approvals=[],
    )

    assert DeterministicMatcher().score(spec, oil) is not None


def _score_formatted_values(
    *,
    oil_sae="5W-40",
    required_sae="5W-40",
    oil_api="SN PLUS",
    minimum_api="SN PLUS",
    oil_acea="A3/B4",
    required_acea="A3/B4",
    oil_oem="VW 502 00",
    required_oem="VW 502 00",
):
    spec = OilRequirement(
        engine_code="E",
        recommended_sae=[required_sae],
        alternative_sae=[],
        minimum_api=minimum_api,
        acea_specs=[required_acea],
        oem_approvals=[required_oem],
        confidence=0.9,
    )
    oil = EngineOil(
        brand="B",
        name="N",
        sae_viscosity=oil_sae,
        api_spec=oil_api,
        acea_specs=[oil_acea],
        oem_approvals=[oil_oem],
    )
    return DeterministicMatcher().score(spec, oil)


@pytest.mark.parametrize(
    ("oil_sae", "required_sae"),
    [
        ("5W-40", "SAE 5W-40"),
        ("sae 5w_40", " 5W.40 "),
        ("SAE J300 5W 40", "5w-40"),
    ],
)
def test_sae_normalization_handles_prefix_spacing_punctuation_and_case(
    oil_sae, required_sae
):
    candidate = _score_formatted_values(
        oil_sae=oil_sae, required_sae=required_sae
    )

    assert candidate is not None
    assert "recommended SAE" in candidate.reasons


@pytest.mark.parametrize(
    ("oil_api", "minimum_api"),
    [
        ("SL", "API SL"),
        ("api sn plus", "SN_PLUS"),
        ("API SN+", "SN-PLUS"),
    ],
)
def test_api_normalization_handles_prefix_spacing_punctuation_and_aliases(
    oil_api, minimum_api
):
    candidate = _score_formatted_values(
        oil_api=oil_api, minimum_api=minimum_api
    )

    assert candidate is not None
    assert "API requirement satisfied" in candidate.reasons


@pytest.mark.parametrize(
    ("oil_acea", "required_acea"),
    [
        ("A3/B4", "ACEA A3/B4"),
        ("acea a3-b4", " A3_B4 "),
        ("A3.B4", "a3 b4"),
    ],
)
def test_acea_normalization_handles_prefix_spacing_punctuation_and_case(
    oil_acea, required_acea
):
    candidate = _score_formatted_values(
        oil_acea=oil_acea, required_acea=required_acea
    )

    assert candidate is not None
    assert "ACEA match" in candidate.reasons


@pytest.mark.parametrize(
    ("oil_oem", "required_oem"),
    [
        ("VW 502 00", "VW502.00"),
        ("vw-502-00", " VW_502 00 "),
        ("Volkswagen 502.00", "VW 502 00"),
        ("Mercedes-Benz 229.5", "MB Approval 229 5"),
    ],
)
def test_oem_normalization_handles_spacing_punctuation_case_and_aliases(
    oil_oem, required_oem
):
    candidate = _score_formatted_values(
        oil_oem=oil_oem, required_oem=required_oem
    )

    assert candidate is not None
    assert "OEM approval match" in candidate.reasons


def test_normalization_does_not_turn_different_specs_into_matches():
    assert _score_formatted_values(oil_sae="5W-30", required_sae="5W-40") is None

    candidate = _score_formatted_values(
        oil_api="SL",
        minimum_api="SN",
        oil_acea="A3/B3",
        required_acea="A3/B4",
        oil_oem="VW 501 00",
        required_oem="VW 502 00",
    )
    assert candidate is None


def test_unrecognized_api_requirement_remains_a_hard_failure():
    assert _score_formatted_values(oil_api="SP", minimum_api="UNKNOWN") is None
