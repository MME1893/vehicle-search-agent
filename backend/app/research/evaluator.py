from urllib.parse import urlparse

from app.research.schemas import (
    EngineOilResearchResult,
    ResearchEvaluation,
    ResearchSource,
    ResearchStatus,
    SourceType,
)

_OFFICIAL = {SourceType.OFFICIAL_MANUAL, SourceType.OFFICIAL_MANUFACTURER}
_SECONDARY = {
    SourceType.LUBRICANT_MANUFACTURER,
    SourceType.SPECIALIZED_DATABASE,
    SourceType.OTHER_TECHNICAL,
}


def _source_identity(source: ResearchSource) -> str:
    if source.domain:
        return source.domain.lower().removeprefix("www.")

    try:
        return (
            (urlparse(source.url).hostname or source.url).lower().removeprefix("www.")
        )
    except ValueError:
        return source.url.lower()


def _supported_spec_claims(
    result: EngineOilResearchResult, claims: list[str]
) -> set[str]:
    normalized = " ".join(claims).upper().replace(" ", "")
    expected = [
        *result.recommended_sae,
        *result.alternative_sae,
        *result.acea_specs,
        *result.oem_approvals,
        *([result.minimum_api] if result.minimum_api else []),
    ]
    return {
        value
        for value in expected
        if claims and value.upper().replace(" ", "") in normalized
    }


def evaluate_research(
    result: EngineOilResearchResult, min_confidence: float
) -> ResearchEvaluation:
    if result.research_status is not ResearchStatus.FOUND:
        return ResearchEvaluation(
            accepted=False,
            needs_review=True,
            reason=f"research status is {result.research_status.value}",
        )
    if not any(
        (
            result.recommended_sae,
            result.alternative_sae,
            result.minimum_api,
            result.acea_specs,
            result.oem_approvals,
        )
    ):
        return ResearchEvaluation(
            accepted=False,
            needs_review=True,
            reason="usable oil specification is missing",
        )
    if result.confidence < min_confidence:
        return ResearchEvaluation(
            accepted=False,
            needs_review=True,
            reason=f"confidence {result.confidence:.2f} is below {min_confidence:.2f}",
        )
    if any(
        source.source_type in _OFFICIAL
        and _supported_spec_claims(result, source.supported_claims)
        for source in result.sources
    ):
        return ResearchEvaluation(
            accepted=True, needs_review=False, reason="credible official evidence"
        )
    domains_by_spec: dict[str, set[str]] = {}
    for source in result.sources:
        if source.source_type not in _SECONDARY:
            continue
        for specification in _supported_spec_claims(result, source.supported_claims):
            domains_by_spec.setdefault(specification, set()).add(
                _source_identity(source)
            )
    if any(len(domains) >= 2 for domains in domains_by_spec.values()):
        return ResearchEvaluation(
            accepted=True,
            needs_review=False,
            reason="two independent credible secondary sources",
        )
    return ResearchEvaluation(
        accepted=False,
        needs_review=True,
        reason="source trust policy is not satisfied",
    )
