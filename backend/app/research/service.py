import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.core.config import Settings
from app.domain.enums import EvaluationStatus, MatchMethod
from app.domain.oil_requirement import OilRequirement
from app.models import EngineOil, ResearchRun, Vehicle
from app.repositories.compatibility_repository import CompatibilityRepository
from app.repositories.engine_oil_repository import EngineOilRepository
from app.repositories.research_run_repository import ResearchRunRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.research.contracts import ResearchProvider
from app.research.errors import ResearchProviderConfigurationError
from app.research.evaluator import evaluate_research
from app.research.schemas import (
    CatalogResearchResult,
    EngineOilResearchResult,
    ProviderOilMatch,
    ResearchedOilProduct,
    ResearchEvaluation,
    ResearchExecution,
)
from app.services.compatibility.compatibility_service import CompatibilityService
from app.services.matching.matcher import Candidate, DeterministicMatcher


@dataclass
class ResolvedResearchProduct:
    product: ResearchedOilProduct
    oil: EngineOil
    newly_created: bool = False


@dataclass
class ResearchOutcome:
    vehicle: Vehicle
    execution: ResearchExecution
    evaluation: ResearchEvaluation
    requirement: OilRequirement | None = None
    candidates: list[Candidate] = field(default_factory=list)
    research_run: ResearchRun | None = None
    resolved_products: list[ResolvedResearchProduct] = field(default_factory=list)
    compatibility_ids: list[int] = field(default_factory=list)

    @property
    def result(self) -> EngineOilResearchResult:
        return self.execution.research

    @property
    def provider_matches(self) -> list[ProviderOilMatch]:
        return self.execution.matches


class ResearchService:
    def __init__(self, db, provider: ResearchProvider, settings: Settings):
        self.db = db
        self.provider = provider
        self.settings = settings
        self.vehicles = VehicleRepository(db)
        self.research_runs = ResearchRunRepository(db)
        self.oils = EngineOilRepository(db)
        self.compatibilities = CompatibilityService(
            CompatibilityRepository(db), self.vehicles, self.oils
        )
        self.matcher = DeterministicMatcher()

    async def execute_vehicle_research(
        self,
        vehicle_id: int,
        *,
        persist: bool = True,
        progress_callback: Callable[[str], None] | None = None,
    ) -> ResearchOutcome:
        outcome = await self.research_vehicle(vehicle_id, progress_callback=progress_callback)
        if not persist:
            if outcome.evaluation.accepted:
                self.find_candidates(outcome)
            return outcome
        if progress_callback:
            progress_callback("saving")
        try:
            self.persist_research_run(outcome)
            if outcome.evaluation.accepted:
                self.sync_recommended_products(outcome)
                if progress_callback:
                    progress_callback("matching")
                self.find_candidates(outcome)
                self.persist_compatibilities(outcome)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return outcome

    async def research_vehicle(
        self,
        vehicle_id: int,
        *,
        progress_callback: Callable[[str], None] | None = None,
    ) -> ResearchOutcome:
        if progress_callback:
            progress_callback("loading_vehicle")
        vehicle = self.vehicles.get_by_id(vehicle_id)
        if not vehicle:
            self.db.rollback()
            raise LookupError("vehicle not found")
        catalog = (
            self.oils.list_all()
            if self.settings.matching_strategy == "provider_catalog"
            else []
        )
        self.db.expunge(vehicle)
        for oil in catalog:
            self.db.expunge(oil)
        self.db.commit()

        started_at = datetime.now(UTC)
        started = time.perf_counter()
        if progress_callback:
            progress_callback("researching")
        if self.settings.matching_strategy == "provider_catalog":
            if not hasattr(self.provider, "research_vehicle_with_catalog"):
                raise ResearchProviderConfigurationError(
                    "MATCHING_STRATEGY=provider_catalog requires a catalog-capable provider"
                )
            provider_result = await self.provider.research_vehicle_with_catalog(vehicle, catalog)
        else:
            provider_result = await self.provider.research_vehicle_oil_spec(vehicle)
        execution = self._coerce_execution(provider_result)
        completed_at = datetime.now(UTC)
        total_duration_ms = round((time.perf_counter() - started) * 1000)

        if progress_callback:
            progress_callback("evaluating")
        result = execution.research
        evaluation = evaluate_research(result, self.settings.research_min_confidence)
        if evaluation.accepted and result.vehicle_id != vehicle.id:
            evaluation = ResearchEvaluation(
                accepted=False,
                needs_review=True,
                reason="research result vehicle_id does not match the requested vehicle",
            )
        if (
            evaluation.accepted
            and vehicle.engine_code
            and result.engine_code
            and vehicle.engine_code.strip().upper() != result.engine_code.strip().upper()
        ):
            evaluation = ResearchEvaluation(
                accepted=False,
                needs_review=True,
                reason="researched engine code does not match the vehicle record",
            )

        requirement = self._build_requirement(vehicle, result) if evaluation.accepted else None
        evaluation_status = (
            EvaluationStatus.ACCEPTED
            if evaluation.accepted
            else EvaluationStatus.NEEDS_REVIEW
            if evaluation.needs_review
            else EvaluationStatus.REJECTED
        )
        run = ResearchRun(
            vehicle_id=vehicle.id,
            provider=execution.provider,
            model=execution.model,
            matching_strategy=self.settings.matching_strategy,
            research_status=result.research_status.value,
            evaluation_status=evaluation_status.value,
            evaluation_reason=evaluation.reason,
            raw_research_text=execution.raw_research_text,
            structured_result=result.model_dump(mode="json"),
            search_queries=execution.search_queries,
            grounding_sources=execution.grounding_sources,
            started_at=started_at,
            completed_at=completed_at,
            stage1_duration_ms=execution.stage1_duration_ms,
            stage2_duration_ms=execution.stage2_duration_ms,
            total_duration_ms=total_duration_ms,
        )
        return ResearchOutcome(vehicle, execution, evaluation, requirement, research_run=run)

    def _coerce_execution(self, value) -> ResearchExecution:
        if isinstance(value, ResearchExecution):
            return value
        if isinstance(value, CatalogResearchResult):
            return ResearchExecution(
                research=value.research,
                matches=value.matches,
                provider=getattr(self.provider, "provider_name", type(self.provider).__name__),
            )
        if isinstance(value, EngineOilResearchResult):
            return ResearchExecution(
                research=value,
                provider=getattr(self.provider, "provider_name", type(self.provider).__name__),
            )
        raise TypeError("research provider must return ResearchExecution")

    @staticmethod
    def _build_requirement(vehicle: Vehicle, result: EngineOilResearchResult) -> OilRequirement:
        return OilRequirement(
            engine_code=result.engine_code or vehicle.engine_code,
            fuel_type=vehicle.fuel_type,
            recommended_sae=list(result.recommended_sae),
            alternative_sae=list(result.alternative_sae),
            minimum_api=result.minimum_api,
            acea_specs=list(result.acea_specs),
            oem_approvals=list(result.oem_approvals),
            confidence=result.confidence,
        )

    def persist_research_run(self, outcome: ResearchOutcome) -> ResearchRun:
        if not outcome.research_run:
            raise ValueError("research outcome has no research run")
        if outcome.research_run.id is None:
            self.db.add(outcome.research_run)
            self.db.flush()
        return outcome.research_run

    def sync_recommended_products(
        self, outcome: ResearchOutcome, *, persist: bool = True
    ) -> list[ResolvedResearchProduct]:
        run = self.persist_research_run(outcome) if persist else outcome.research_run
        resolved = []
        for product in outcome.result.recommended_products:
            oil = self.oils.find_researched_product(
                product.brand, product.name, product.sae_viscosity, product.api_spec
            )
            newly_created = False
            if (
                oil is None
                and all(
                    value.strip()
                    for value in (product.brand, product.name, product.sae_viscosity)
                )
                and product.source_urls
            ):
                values = {
                    "brand": product.brand.strip(),
                    "name": product.name.strip(),
                    "sae_viscosity": product.sae_viscosity.strip().upper(),
                    "api_spec": product.api_spec,
                    "acea_specs": product.acea_specs,
                    "base_type": product.base_type,
                    "oem_approvals": product.oem_approvals,
                    "created_from_research_run_id": run.id if run else None,
                }
                oil = self.oils.create(values) if persist else EngineOil(**values)
                newly_created = persist
            if oil is not None:
                resolved.append(ResolvedResearchProduct(product, oil, newly_created))
        outcome.resolved_products = resolved
        return resolved

    def find_candidates(self, outcome: ResearchOutcome) -> list[Candidate]:
        if self.settings.matching_strategy != "deterministic" or not outcome.requirement:
            outcome.candidates = []
            return []
        catalog = self.oils.list_all()
        if not outcome.resolved_products:
            self.sync_recommended_products(outcome, persist=False)
        known_ids = {oil.id for oil in catalog if oil.id is not None}
        catalog.extend(
            item.oil
            for item in outcome.resolved_products
            if item.oil.id is None or item.oil.id not in known_ids
        )
        outcome.candidates = self.matcher.find_candidates(outcome.requirement, catalog)
        return outcome.candidates

    def persist_compatibilities(self, outcome: ResearchOutcome) -> int:
        if not outcome.research_run or outcome.research_run.id is None:
            raise ValueError("research run must be persisted before compatibilities")
        direct_product_ids = {
            item.oil.id for item in outcome.resolved_products if item.oil.id is not None
        }
        if self.settings.matching_strategy == "provider_catalog":
            events = [
                (
                    match.engine_oil_id,
                    match.compatibility_type,
                    match.match_score,
                    match.confidence_score,
                    "; ".join(match.reasons),
                    MatchMethod.PROVIDER_CATALOG_MATCH,
                )
                for match in outcome.provider_matches
            ]
        else:
            events = [
                (
                    candidate.oil.id,
                    "RECOMMENDED" if "recommended SAE" in candidate.reasons else "COMPATIBLE",
                    candidate.score,
                    outcome.result.confidence,
                    "; ".join(candidate.reasons),
                    MatchMethod.DIRECT_RESEARCH_PRODUCT
                    if candidate.oil.id in direct_product_ids
                    else MatchMethod.DETERMINISTIC_SPEC_MATCH,
                )
                for candidate in outcome.candidates
                if candidate.oil.id is not None
            ]
        outcome.compatibility_ids = []
        for oil_id, kind, score, confidence, reason, method in events:
            event = self.compatibilities.create_event(
                {
                    "vehicle_id": outcome.vehicle.id,
                    "engine_oil_id": oil_id,
                    "research_run_id": outcome.research_run.id,
                    "match_method": method.value,
                    "compatibility_type": getattr(kind, "value", kind),
                    "match_score": score,
                    "confidence_score": confidence,
                    "reason": reason,
                    "created_by": "AGENT",
                }
            )
            outcome.compatibility_ids.append(event.id)
        return len(outcome.compatibility_ids)
