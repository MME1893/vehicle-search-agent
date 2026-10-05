from dataclasses import dataclass, field


@dataclass(frozen=True)
class OilRequirement:
    engine_code: str | None
    fuel_type: str | None = None
    recommended_sae: list[str] = field(default_factory=list)
    alternative_sae: list[str] = field(default_factory=list)
    minimum_api: str | None = None
    acea_specs: list[str] = field(default_factory=list)
    oem_approvals: list[str] = field(default_factory=list)
    confidence: float = 0.0
