from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class ResearchStatus(str, Enum):
    FOUND = "FOUND"
    INSUFFICIENT = "INSUFFICIENT"


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
    acea_spec: str | None = None
    base_type: str | None = None
    oem_approvals: list[str] = Field(default_factory=list)
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
