import logging
import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from app.domain.oil_requirement import OilRequirement
from app.models import EngineOil
from app.services.matching.rules import (
    api_satisfies,
    extract_api_categories,
    normalize_fuel_type,
)
from app.services.matching.scoring import MatchWeights, capped_score

_SAE_PREFIX = re.compile(r"^(?:SAE(?:\s+J\s*300)?\b[\s:._-]*)+", re.IGNORECASE)
_ACEA_PREFIX = re.compile(r"^ACEA\b[\s:._-]*", re.IGNORECASE)
_NON_ALPHANUMERIC = re.compile(r"[^A-Z0-9]+")


def _comparison_text(value: str | None) -> str:
    """Prepare external/catalog text without changing its stored representation."""
    if not value:
        return ""
    return unicodedata.normalize("NFKC", value).strip().upper()


def _compact(value: str) -> str:
    return _NON_ALPHANUMERIC.sub("", value)


def _normalize_sae(value: str | None) -> str:
    normalized = _SAE_PREFIX.sub("", _comparison_text(value))
    return _compact(normalized)


def _normalize_acea(value: str | None) -> str:
    normalized = _ACEA_PREFIX.sub("", _comparison_text(value))
    return _compact(normalized)


def _normalize_oem_approval(value: str | None) -> str:
    normalized = _compact(_comparison_text(value))
    aliases = (
        ("VOLKSWAGENAG", "VW"),
        ("VOLKSWAGEN", "VW"),
        ("MERCEDESBENZ", "MB"),
        ("MERCEDES", "MB"),
        ("GENERALMOTORS", "GM"),
        ("BMWLONGLIFE", "BMWLL"),
    )
    for alias, canonical in aliases:
        if normalized.startswith(alias):
            normalized = canonical + normalized[len(alias) :]
            break

    # These words label an approval but are not part of its identifier.
    for prefix in ("MBAPPROVAL", "VWAPPROVAL", "VWSTANDARD"):
        if normalized.startswith(prefix):
            normalized = prefix[:2] + normalized[len(prefix) :]
            break
    return normalized


def _normalized_overlap(
    left: Iterable[str], right: Iterable[str], normalizer: Callable[[str | None], str]
) -> bool:
    right_values = {normalized for item in right if (normalized := normalizer(item))}
    return any(
        normalized in right_values
        for item in left
        if (normalized := normalizer(item))
    )


@dataclass(frozen=True)
class Candidate:
    oil: EngineOil
    score: int
    reasons: list[str]


class DeterministicMatcher:
    def __init__(self, weights: MatchWeights | None = None):
        self.weights = weights or MatchWeights()

    def score(self, requirement: OilRequirement, oil: EngineOil) -> Candidate | None:
        points, reasons = [], []
        oil_sae = _normalize_sae(oil.sae_viscosity)
        if oil_sae and oil_sae in {
            _normalize_sae(value) for value in requirement.recommended_sae
        }:
            points.append(self.weights.recommended_sae)
            reasons.append("recommended SAE")
        elif oil_sae and oil_sae in {
            _normalize_sae(value) for value in requirement.alternative_sae
        }:
            points.append(self.weights.alternative_sae)
            reasons.append("alternative SAE")
        else:
            return None
        fuel_type = normalize_fuel_type(requirement.fuel_type)
        if requirement.minimum_api and not extract_api_categories(requirement.minimum_api):
            logging.getLogger(__name__).warning(
                "Unknown minimum API category %r", requirement.minimum_api
            )
            return None
        if requirement.minimum_api and not api_satisfies(
            oil.api_spec, requirement.minimum_api, fuel_type
        ):
            return None
        if requirement.minimum_api:
            points.append(self.weights.api)
            reasons.append("API requirement satisfied")
            reasons.append(
                f"API {oil.api_spec} satisfies {requirement.minimum_api} minimum"
            )
        else:
            points.append(self.weights.api)
        acea_matches = _normalized_overlap(
            oil.acea_specs or [],
            requirement.acea_specs,
            _normalize_acea,
        )
        if requirement.acea_specs and not acea_matches:
            return None
        if acea_matches:
            points.append(self.weights.acea)
            reasons.append("ACEA match")
        oem_matches = _normalized_overlap(
            oil.oem_approvals or [], requirement.oem_approvals, _normalize_oem_approval
        )
        if requirement.oem_approvals and not oem_matches:
            return None
        if oem_matches:
            points.append(self.weights.oem)
            reasons.append("OEM approval match")
        return Candidate(oil, capped_score(*points), reasons)

    def find_candidates(
        self, requirement: OilRequirement, oils: list[EngineOil]
    ) -> list[Candidate]:
        return sorted(
            (c for oil in oils if (c := self.score(requirement, oil))),
            key=lambda c: c.score,
            reverse=True,
        )
