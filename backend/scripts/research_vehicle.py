import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.errors import ResearchProviderError
from app.agents.factory import create_research_provider
from app.agents.gemini_research_adapter import GeminiResearchAdapter
from app.agents.opencode_research_agent import OpenCodeResearchAgent
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.repositories.vehicle_repository import VehicleRepository
from app.services.research import ResearchService


def create_script_session():
    """Use the published PostgreSQL port when run on the Windows host."""
    configured_engine = SessionLocal.kw.get("bind")
    if configured_engine is None or configured_engine.url.host != "postgres":
        return SessionLocal(), None
    local_engine = create_engine(
        configured_engine.url.set(host="127.0.0.1"), pool_pre_ping=True
    )
    options = {key: value for key, value in SessionLocal.kw.items() if key != "bind"}
    return sessionmaker(bind=local_engine, **options)(), local_engine


async def main(
    vehicle_id: int,
    save: bool,
    matching_strategy: str | None = None,
) -> int:
    settings = get_settings()
    if matching_strategy:
        settings = settings.model_copy(update={"matching_strategy": matching_strategy})
    configure_logging(settings.log_level)
    db, local_engine = create_script_session()
    provider = None
    try:
        print(f"[1/6] Loading vehicle {vehicle_id}...", flush=True)
        try:
            vehicle = VehicleRepository(db).get_by_id(vehicle_id)
        except SQLAlchemyError as exc:
            print(f"ERROR: Database connection failed: {exc.__class__.__name__}")
            return 1
        if not vehicle:
            print(f"ERROR: Vehicle {vehicle_id} was not found.", flush=True)
            return 1

        provider_label = {
            "gemini": "Gemini",
            "openrouter": "OpenRouter",
            "opencode": "OpenCode",
        }[settings.research_provider]
        strategy_label = settings.matching_strategy
        if strategy_label == "provider_catalog":
            strategy_label += " (experimental)"

        print(f"\n[2/6] Research provider: {provider_label}", flush=True)
        print(f"Matching strategy: {strategy_label}", flush=True)
        try:
            provider = create_research_provider(settings)
        except ResearchProviderError as exc:
            print(f"ERROR: {exc}", flush=True)
            return 1

        if isinstance(provider, GeminiResearchAdapter):
            print(f"Model: {provider.client.model}", flush=True)
            print("Google Search: enabled", flush=True)
            if settings.matching_strategy == "provider_catalog":
                print(
                    f"Catalog oils sent: {len(ResearchService(db, provider, settings).oils.list_all())}",
                    flush=True,
                )
        elif isinstance(provider, OpenCodeResearchAgent):
            version = await provider.client.get_version()
            print(f"OpenCode version: {version}", flush=True)
            print(f"Agent: {provider.client.agent}", flush=True)
            if provider.client.model:
                print(f"Model override: {provider.client.model}", flush=True)
        else:
            print(f"Model: {provider.client.model}", flush=True)

        service = ResearchService(db, provider, settings)
        operation = (
            "grounded catalog research"
            if settings.matching_strategy == "provider_catalog"
            else "Google Search research"
            if settings.research_provider == "gemini"
            else "web research"
        )
        print(f"\n[3/6] Starting {provider_label} {operation}...", flush=True)
        started = time.perf_counter()
        try:
            outcome = await service.execute_vehicle_research(
                vehicle_id,
                persist=save,
            )
        except (ResearchProviderError, LookupError) as exc:
            elapsed = time.perf_counter() - started
            if isinstance(provider, GeminiResearchAdapter):
                if provider.client.last_grounded_duration is not None:
                    print(
                        "Stage 1 duration: "
                        f"{provider.client.last_grounded_duration:.1f}s",
                        flush=True,
                    )
                if provider.client.last_extraction_duration is not None:
                    print(
                        "Stage 2 duration: "
                        f"{provider.client.last_extraction_duration:.1f}s",
                        flush=True,
                    )
                else:
                    print("Stage 2 duration: not started", flush=True)
                grounding = provider.client.last_grounding
                print(f"Google Search queries: {len(grounding.queries)}", flush=True)
                print(f"Grounded sources: {len(grounding.sources)}", flush=True)
                print("Recommended products: unavailable", flush=True)
            print(f"Total research duration: {elapsed:.1f}s", flush=True)
            print(f"ERROR: {provider_label} research failed: {exc}", flush=True)
            return 1
        elapsed = time.perf_counter() - started

        if isinstance(provider, GeminiResearchAdapter):
            execution = outcome.execution
            print(
                f"Stage 1 duration: {(execution.stage1_duration_ms or 0) / 1000:.1f}s",
                flush=True,
            )
            print(f"Google Search queries: {len(execution.search_queries)}", flush=True)
            for query in execution.search_queries:
                print(f"- query: {query}", flush=True)
            print(f"Grounded sources: {len(execution.grounding_sources)}", flush=True)
            for source in execution.grounding_sources:
                print(
                    f"- source: {source.get('title') or '(untitled)'}: "
                    f"{source.get('url') or '(no URI)'}",
                    flush=True,
                )
            print(
                f"Stage 2 duration: {(execution.stage2_duration_ms or 0) / 1000:.1f}s",
                flush=True,
            )
            print(
                f"Recommended products: {len(outcome.result.recommended_products)}",
                flush=True,
            )
        print(f"\n[4/6] Total research duration: {elapsed:.1f}s", flush=True)
        print("\nResearch:", flush=True)
        print(
            json.dumps(
                outcome.result.model_dump(mode="json"), indent=2, ensure_ascii=False
            ),
            flush=True,
        )

        print("\n[5/6] Evidence evaluation...", flush=True)
        print(f"Accepted: {'YES' if outcome.evaluation.accepted else 'NO'}", flush=True)
        print(f"Reason: {outcome.evaluation.reason}", flush=True)
        if not outcome.evaluation.accepted:
            if save:
                print(f"ResearchRun id={outcome.research_run.id} saved.", flush=True)
            print("\n[6/6] Matching skipped (evidence not accepted).", flush=True)
            if not save:
                print("\nDry run: nothing was saved.", flush=True)
            return 0

        if settings.matching_strategy == "deterministic":
            print("\n[6/6] Deterministic matching...", flush=True)
            matches = outcome.candidates
            print(f"Compatible oils: {len(matches)}", flush=True)
            for item in matches:
                print(
                    f"- oil_id={item.oil.id} {item.oil.brand} {item.oil.name} "
                    f"score={item.score} reasons={', '.join(item.reasons)}",
                    flush=True,
                )
        else:
            print("\n[6/6] Provider catalog matching...", flush=True)
            print(f"Selected oils: {len(outcome.provider_matches)}", flush=True)
            for item in outcome.provider_matches:
                print(
                    f"- oil_id={item.engine_oil_id} type={item.compatibility_type} "
                    f"score={item.match_score} reasons={', '.join(item.reasons)}",
                    flush=True,
                )

        if save:
            saved = len(outcome.compatibility_ids)
            new_ids = [
                item.oil.id for item in outcome.resolved_products if item.newly_created
            ]
            print(
                f"\nSaved ResearchRun id={outcome.research_run.id}; "
                f"new products={new_ids}; compatibilities={saved} "
                f"ids={outcome.compatibility_ids}",
                flush=True,
            )
        else:
            print("\nDry run: nothing was saved.", flush=True)
        return 0
    finally:
        if isinstance(provider, GeminiResearchAdapter):
            await provider.client.aclose()
        db.close()
        if local_engine is not None:
            local_engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Research one vehicle's oil specification"
    )
    parser.add_argument("vehicle_id", type=int)
    parser.add_argument("--save", action="store_true")
    parser.add_argument(
        "--matching-strategy",
        choices=["deterministic", "provider_catalog"],
        help="Override MATCHING_STRATEGY for this process",
    )
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(main(args.vehicle_id, args.save, args.matching_strategy))
    )
