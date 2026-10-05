from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from app.domain.enums import ResearchStatus


class SourceType(str, Enum):
    OFFICIAL_MANUAL = "OFFICIAL_MANUAL"
    OFFICIAL_MANUFACTURER = "OFFICIAL_MANUFACTURER"
    LUBRICANT_MANUFACTURER = "LUBRICANT_MANUFACTURER"
    SPECIALIZED_DATABASE = "SPECIALIZED_DATABASE"
    OTHER_TECHNICAL = "OTHER_TECHNICAL"
    LOW_QUALITY = "LOW_QUALITY"


class ResearchSource(BaseModel):
    title: str
    url: str
    domain: str | None = None
    source_type: SourceType
    supported_claims: list[str] = Field(default_factory=list)


class ResearchedOilProduct(BaseModel):
    brand: str
    name: str
    sae_viscosity: str
    api_spec: str | None = None
    acea_specs: list[str] = Field(default_factory=list)
    ilsac_spec: str | None = None
    base_type: str | None = None
    oem_approvals: list[str] = Field(default_factory=list)
    package_volume_liters: Decimal | None = Field(
        None, gt=0, max_digits=6, decimal_places=2
    )
    package_volume_label: str | None = None
    claimed_service_interval_km: int | None = Field(None, gt=0)
    recommendation_reason: str | None = None
    source_urls: list[str] = Field(default_factory=list)


class EngineOilResearchResult(BaseModel):
    research_status: ResearchStatus
    vehicle_id: int
    engine_code: str | None = None
    recommended_sae: list[str] = Field(default_factory=list)
    alternative_sae: list[str] = Field(default_factory=list)
    minimum_api: str | None = None
    acea_specs: list[str] = Field(default_factory=list)
    oem_approvals: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    sources: list[ResearchSource] = Field(default_factory=list)
    recommended_products: list[ResearchedOilProduct] = Field(default_factory=list)
    notes: str | None = None


class ResearchEvaluation(BaseModel):
    accepted: bool
    needs_review: bool
    reason: str


class ProviderOilMatch(BaseModel):
    engine_oil_id: int
    compatibility_type: Literal["RECOMMENDED", "COMPATIBLE", "CONDITIONAL"]
    match_score: int = Field(ge=0, le=100)
    confidence_score: float = Field(ge=0.0, le=1.0)
    reasons: list[str] = Field(default_factory=list)


class CatalogResearchResult(BaseModel):
    research: EngineOilResearchResult
    matches: list[ProviderOilMatch] = Field(default_factory=list)


@dataclass(frozen=True)
class ResearchExecution:
    research: EngineOilResearchResult
    matches: list[ProviderOilMatch] = field(default_factory=list)
    provider: str = "unknown"
    model: str | None = None
    raw_research_text: str | None = None
    search_queries: list[str] = field(default_factory=list)
    grounding_sources: list[dict] = field(default_factory=list)
    stage1_duration_ms: int | None = None
    stage2_duration_ms: int | None = None

    def __getattr__(self, name):
        """Delegate research fields for adapters migrating to this explicit envelope."""
        return getattr(self.research, name)
