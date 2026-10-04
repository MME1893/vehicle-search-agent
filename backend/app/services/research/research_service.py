import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.agents.errors import ResearchProviderConfigurationError
from app.agents.evaluator import evaluate_research
from app.agents.protocols import CatalogResearchProvider, ResearchProvider
from app.agents.schemas import (
    EngineOilResearchResult,
    ProviderOilMatch,
    ResearchedOilProduct,
    ResearchEvaluation,
    ResearchSource,
    SourceType,
)
from app.core.config import Settings
from app.models import EngineOil, EngineSpec, ResearchRun, Vehicle
from app.repositories.compatibility_history_repository import (
    CompatibilityHistoryRepository,
)
from app.repositories.compatibility_repository import CompatibilityRepository
from app.repositories.engine_oil_repository import EngineOilRepository
from app.repositories.engine_spec_repository import EngineSpecRepository
from app.repositories.research_run_repository import ResearchRunRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.services.compatibility.compatibility_service import CompatibilityService
from app.services.matching.matcher import Candidate, DeterministicMatcher

logger = logging.getLogger(__name__)


@dataclass
class ResolvedResearchProduct:
    product: ResearchedOilProduct
    oil: EngineOil
    newly_created: bool = False


@dataclass
class ResearchOutcome:
    vehicle: Vehicle
    result: EngineOilResearchResult
    evaluation: ResearchEvaluation
    engine_spec: EngineSpec | None = None
    candidates: list[Candidate] = field(default_factory=list)
    provider_matches: list[ProviderOilMatch] = field(default_factory=list)
    research_run: ResearchRun | None = None
    resolved_products: list[ResolvedResearchProduct] = field(default_factory=list)
    compatibility_ids: list[int] = field(default_factory=list)
    history_ids: list[int] = field(default_factory=list)


_SOURCE_RANK = {
    SourceType.OFFICIAL_MANUAL: 0,
    SourceType.OFFICIAL_MANUFACTURER: 1,
    SourceType.LUBRICANT_MANUFACTURER: 2,
    SourceType.SPECIALIZED_DATABASE: 3,
    SourceType.OTHER_TECHNICAL: 4,
    SourceType.LOW_QUALITY: 5,
}


class ResearchService:
    def __init__(
        self,
        db,
        provider: ResearchProvider,
        settings: Settings,
    ):
        self.db = db
        self.provider = provider
        self.settings = settings
        self.vehicles = VehicleRepository(db)
        self.specs = EngineSpecRepository(db)
        self.research_runs = ResearchRunRepository(db)
        self.oils = EngineOilRepository(db)
        self.compatibility_history = CompatibilityHistoryRepository(db)
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
        """Run the complete research, persistence, and matching workflow."""

        def report(step: str) -> None:
            if progress_callback is not None:
                progress_callback(step)

        outcome = await self.research_vehicle(
            vehicle_id,
            progress_callback=progress_callback,
        )

        if not outcome.evaluation.accepted:
            if persist:
                report("saving")
                self.persist_research_run(outcome)
            return outcome

        report("saving")
        if persist:
            self.persist_engine_spec(outcome)

        report("matching")
        self.find_candidates(outcome)
        if persist:
            self.persist_compatibilities(outcome)
        return outcome

    async def research_vehicle(
        self,
        vehicle_id: int,
        *,
        progress_callback: Callable[[str], None] | None = None,
    ) -> ResearchOutcome:
        if progress_callback is not None:
            progress_callback("loading_vehicle")
        vehicle = self.vehicles.get_by_id(vehicle_id)
        if not vehicle:
            raise LookupError("vehicle not found")
        provider_matches: list[ProviderOilMatch] = []
        started_at = datetime.now(UTC)
        started = time.perf_counter()
        if progress_callback is not None:
            progress_callback("researching")
        if self.settings.matching_strategy == "provider_catalog":
            if not isinstance(self.provider, CatalogResearchProvider):
                raise ResearchProviderConfigurationError(
                    "MATCHING_STRATEGY=provider_catalog requires a catalog-capable "
                    "Gemini provider"
                )
            catalog_result = await self.provider.research_vehicle_with_catalog(
                vehicle, self.oils.list_all()
            )
            result = catalog_result.research
            provider_matches = catalog_result.matches
        else:
            result = await self.provider.research_vehicle_oil_spec(vehicle)
        completed_at = datetime.now(UTC)
        total_duration_ms = round((time.perf_counter() - started) * 1000)
        evaluation_started = time.perf_counter()
        if progress_callback is not None:
            progress_callback("evaluating")
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
            and vehicle.engine_code.strip().upper()
            != result.engine_code.strip().upper()
        ):
            evaluation = ResearchEvaluation(
                accepted=False,
                needs_review=True,
                reason="researched engine code does not match the vehicle record",
            )
        if evaluation.accepted and not (result.engine_code or vehicle.engine_code):
            evaluation = ResearchEvaluation(
                accepted=False,
                needs_review=True,
                reason="engine code is required to persist the engine specification",
            )
        logger.info(
            "Evidence accepted=%s reason=%s elapsed=%.3fs",
            evaluation.accepted,
            evaluation.reason,
            time.perf_counter() - evaluation_started,
        )
        spec = self._build_engine_spec(vehicle, result) if evaluation.accepted else None
        client = getattr(self.provider, "client", None)
        grounding = getattr(client, "last_grounding", None)
        research_run = ResearchRun(
            vehicle_id=vehicle.id,
            provider=getattr(
                self.provider, "provider_name", type(self.provider).__name__
            ),
            model=getattr(client, "model", None),
            matching_strategy=self.settings.matching_strategy,
            status=result.research_status.value,
            raw_research_text=getattr(client, "last_research_text", None),
            structured_result=result.model_dump(mode="json"),
            search_queries=list(getattr(grounding, "queries", []) or []),
            grounding_sources=[
                {"title": item.title, "url": item.uri}
                for item in (getattr(grounding, "sources", []) or [])
            ],
            started_at=started_at,
            completed_at=completed_at,
            stage1_duration_ms=self._duration_ms(
                getattr(client, "last_grounded_duration", None)
            ),
            stage2_duration_ms=self._duration_ms(
                getattr(client, "last_extraction_duration", None)
            ),
            total_duration_ms=total_duration_ms,
        )
        return ResearchOutcome(
            vehicle=vehicle,
            result=result,
            evaluation=evaluation,
            engine_spec=spec,
            provider_matches=provider_matches,
            research_run=research_run,
        )

    @staticmethod
    def _duration_ms(value: float | None) -> int | None:
        return round(value * 1000) if value is not None else None

    @staticmethod
    def _strongest_source(sources: list[ResearchSource]) -> ResearchSource | None:
        return (
            min(sources, key=lambda source: _SOURCE_RANK[source.source_type])
            if sources
            else None
        )

    def _build_engine_spec(
        self, vehicle: Vehicle, result: EngineOilResearchResult
    ) -> EngineSpec:
        source = self._strongest_source(result.sources)
        return EngineSpec(
            engine_code=result.engine_code or vehicle.engine_code,
            recommended_sae=result.recommended_sae,
            alternative_sae=result.alternative_sae,
            minimum_api=result.minimum_api,
            acea_specs=result.acea_specs,
            oem_approvals=result.oem_approvals,
            source=source.title if source else None,
            source_url=source.url if source else None,
            evidence={
                "sources": [item.model_dump(mode="json") for item in result.sources],
                "recommended_products": [
                    item.model_dump(mode="json") for item in result.recommended_products
                ],
                "notes": result.notes,
                "vehicle_id": result.vehicle_id,
            },
            confidence=result.confidence,
            status="VERIFIED",
        )

    def persist_research_run(self, outcome: ResearchOutcome) -> ResearchRun:
        if not outcome.research_run:
            raise ValueError("research outcome has no research run")
        if outcome.research_run.id is not None:
            return outcome.research_run
        outcome.research_run = self.research_runs.create(
            {
                column.name: getattr(outcome.research_run, column.name)
                for column in ResearchRun.__table__.columns
                if column.name not in {"id", "created_at"}
            }
        )
        logger.info("ResearchRun persisted id=%s", outcome.research_run.id)
        return outcome.research_run

    def sync_recommended_products(
        self, outcome: ResearchOutcome, *, persist: bool = True
    ) -> list[ResolvedResearchProduct]:
        if persist:
            run = self.persist_research_run(outcome)
        else:
            run = outcome.research_run
        resolved: list[ResolvedResearchProduct] = []
        for product in outcome.result.recommended_products:
            oil = self.oils.find_researched_product(
                product.brand,
                product.name,
                product.sae_viscosity,
                product.api_spec,
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
                    "acea_spec": product.acea_spec,
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

    def persist_engine_spec(self, outcome: ResearchOutcome) -> EngineSpec:
        if not outcome.evaluation.accepted or not outcome.engine_spec:
            raise ValueError("research outcome is not accepted")
        run = self.persist_research_run(outcome)
        self.sync_recommended_products(outcome)
        outcome.engine_spec.research_run_id = run.id
        spec = self.specs.create(
            {
                column.name: getattr(outcome.engine_spec, column.name)
                for column in EngineSpec.__table__.columns
                if column.name not in {"id", "created_at", "updated_at"}
            }
        )
        outcome.engine_spec = spec
        logger.info("EngineSpec persisted id=%s", spec.id)
        return spec

    def find_candidates(self, outcome: ResearchOutcome) -> list[Candidate]:
        if self.settings.matching_strategy != "deterministic":
            outcome.candidates = []
            return outcome.candidates
        if not outcome.engine_spec:
            return []
        matching_started = time.perf_counter()
        catalog = self.oils.list_all()
        if not outcome.resolved_products:
            self.sync_recommended_products(outcome, persist=False)
        known_ids = {oil.id for oil in catalog if oil.id is not None}
        catalog.extend(
            item.oil
            for item in outcome.resolved_products
            if item.oil.id is None or item.oil.id not in known_ids
        )
        outcome.candidates = self.matcher.find_candidates(outcome.engine_spec, catalog)
        logger.info(
            "Matcher candidates=%s elapsed=%.3fs",
            len(outcome.candidates),
            time.perf_counter() - matching_started,
        )
        return outcome.candidates

    def persist_compatibilities(self, outcome: ResearchOutcome) -> int:
        if not outcome.research_run or outcome.research_run.id is None:
            raise ValueError("research run must be persisted before compatibilities")
        if not outcome.engine_spec or outcome.engine_spec.id is None:
            raise ValueError("engine spec must be persisted before compatibilities")
        saved = 0
        direct_product_ids = {
            item.oil.id for item in outcome.resolved_products if item.oil.id is not None
        }
        outcome.compatibility_ids = []
        outcome.history_ids = []
        if self.settings.matching_strategy == "provider_catalog":
            for match in outcome.provider_matches:
                compatibility = self.compatibilities.save(
                    {
                        "vehicle_id": outcome.vehicle.id,
                        "engine_oil_id": match.engine_oil_id,
                        "compatibility_type": match.compatibility_type,
                        "match_score": match.match_score,
                        "confidence_score": match.confidence_score,
                        "reason": "; ".join(match.reasons),
                        "created_by": "AGENT",
                        "review_status": "PENDING",
                        "research_run_id": outcome.research_run.id,
                        "engine_spec_id": outcome.engine_spec.id,
                    }
                )
                self._append_history(outcome, compatibility, "DIRECT_RESEARCH_PRODUCT")
                saved += 1
            logger.info("Provider compatibilities saved=%s", saved)
            return saved
        for candidate in outcome.candidates:
            if candidate.oil.id is None:
                continue
            recommended = "recommended SAE" in candidate.reasons
            compatibility = self.compatibilities.save(
                {
                    "vehicle_id": outcome.vehicle.id,
                    "engine_oil_id": candidate.oil.id,
                    "compatibility_type": "RECOMMENDED"
                    if recommended
                    else "COMPATIBLE",
                    "match_score": candidate.score,
                    "confidence_score": outcome.result.confidence,
                    "reason": "; ".join(candidate.reasons),
                    "created_by": "AGENT",
                    "review_status": "PENDING",
                    "research_run_id": outcome.research_run.id,
                    "engine_spec_id": outcome.engine_spec.id,
                }
            )
            match_method = (
                "DIRECT_RESEARCH_PRODUCT"
                if candidate.oil.id in direct_product_ids
                else "DETERMINISTIC_SPEC_MATCH"
            )
            self._append_history(outcome, compatibility, match_method)
            saved += 1
        logger.info("Compatibilities saved=%s", saved)
        return saved

    def _append_history(
        self, outcome: ResearchOutcome, compatibility, match_method: str
    ) -> None:
        history = self.compatibility_history.create(
            {
                "compatibility_id": compatibility.id,
                "vehicle_id": compatibility.vehicle_id,
                "engine_oil_id": compatibility.engine_oil_id,
                "research_run_id": outcome.research_run.id,
                "engine_spec_id": outcome.engine_spec.id,
                "match_method": match_method,
                "compatibility_type": compatibility.compatibility_type,
                "match_score": compatibility.match_score,
                "confidence_score": compatibility.confidence_score,
                "reason": compatibility.reason,
            }
        )
        outcome.compatibility_ids.append(compatibility.id)
        outcome.history_ids.append(history.id)
