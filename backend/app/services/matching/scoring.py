from dataclasses import dataclass


@dataclass(frozen=True)
class MatchWeights:
    recommended_sae: int = 30
    alternative_sae: int = 15
    api: int = 20
    acea: int = 25
    oem: int = 25


def capped_score(*parts: int) -> int:
    return min(100, sum(parts))
