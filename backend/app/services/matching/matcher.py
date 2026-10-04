import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from app.core.constants import API_RANK
from app.domain.oil_requirement import OilRequirement
from app.models import EngineOil
from app.services.matching.rules import api_satisfies
from app.services.matching.scoring import MatchWeights, capped_score

_SAE_PREFIX = re.compile(r"^(?:SAE(?:\s+J\s*300)?\b[\s:._-]*)+", re.IGNORECASE)
_API_PREFIX = re.compile(
    r"^(?:(?:MINIMUM|MIN)\s+)?API\b[\s:._-]*", re.IGNORECASE
)
_API_CATEGORY = re.compile(r"(?<![A-Z0-9])(?:SN\s+PLUS|S[A-Z])(?![A-Z0-9])")
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


def _normalize_api(value: str | None) -> str:
    normalized = _API_PREFIX.sub("", _comparison_text(value))
    normalized = re.sub(r"\bSN\s*\+", "SN PLUS", normalized)
    normalized = re.sub(r"[._-]+", " ", normalized)

    # Extract known gasoline categories so additional labels (for example
    # "API Service Category") cannot make equivalent API values compare unequal.
    categories: list[str] = []
    for match in _API_CATEGORY.finditer(normalized):
        category = " ".join(match.group().split())
        if category in API_RANK and category not in categories:
            categories.append(category)
    return "/".join(categories)


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
        oil_api = _normalize_api(oil.api_spec)
        minimum_api = _normalize_api(requirement.minimum_api)
        if requirement.minimum_api and (
            not minimum_api or not api_satisfies(oil_api, minimum_api)
        ):
            return None
        if api_satisfies(oil_api, minimum_api):
            points.append(self.weights.api)
            reasons.append("API requirement satisfied")
        if _normalized_overlap(
            oil.acea_specs or [],
            requirement.acea_specs,
            _normalize_acea,
        ):
            points.append(self.weights.acea)
            reasons.append("ACEA match")
        if _normalized_overlap(
            oil.oem_approvals, requirement.oem_approvals, _normalize_oem_approval
        ):
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
