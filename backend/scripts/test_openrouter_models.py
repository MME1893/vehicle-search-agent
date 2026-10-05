"""Live OpenRouter model smoke test for the two free research candidates.

Requires OPENROUTER_API_KEY. This intentionally uses the application's real
OpenRouter research provider so it verifies server-tool web search, JSON
parsing/repair, and the final Pydantic contract together.
"""

import argparse
import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.research.providers.openrouter.client import OpenRouterClient
from app.research.providers.openrouter.provider import OpenRouterResearchProvider

DEFAULT_MODELS = (
    "qwen/qwen3.8-27b:free",
    "apodex/apodex-1.1-mini:free",

    # Strong new candidates
    "nvidia/nemotron-3-super-120b-a12b:free",
    "dots-studio/dots-3-note-preview:free",
    "google/gemma-4-31b-it:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "inclusionai/ling-3.1-flash",

    # Secondary candidates
    "thinkingmachines/inkling:free",
    "google/gemma-4-26b-a4b-it:free",
    "stealth/space-bunny-alpha",
)

def vehicle():
    return SimpleNamespace(
        id=312,
        manufacturer="Peugeot",
        model="206",
        trim="Type 5 (Iran market)",
        production_year_from=2003,
        production_year_to=2021,
        engine_code="TU5",
        engine_displacement=1587,
        fuel_type="gasoline",
    )


async def run_model(model: str) -> bool | None:
    base = get_settings()
    settings = base.model_copy(
        update={
            "openrouter_model": model,
            "research_web_search_enabled": True,
        }
    )
    client = OpenRouterClient(settings)
    provider = OpenRouterResearchProvider(client, settings)
    started = time.perf_counter()
    print(f"\n=== {model} ===", flush=True)
    try:
        execution = await provider.research_vehicle_oil_spec(vehicle())
    except Exception as exc:  # live diagnostic script: show provider failure verbatim
        elapsed = time.perf_counter() - started
        if "rate limit" in str(exc).lower():
            print(f"INCONCLUSIVE ({elapsed:.1f}s): {exc}", flush=True)
            return None
        print(f"FAIL ({elapsed:.1f}s): {exc}", flush=True)
        return False
    finally:
        await provider.aclose()

    result = execution.research
    print(f"PASS ({time.perf_counter() - started:.1f}s)", flush=True)
    print(f"status: {result.research_status.value}")
    print(f"SAE: {', '.join(result.recommended_sae) or '-'}")
    print(f"API: {result.minimum_api or '-'}")
    print(f"sources: {len(result.sources)}")
    for source in result.sources:
        print(f"- {source.title}: {source.url}")
    return True


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("models", nargs="*", default=list(DEFAULT_MODELS))
    args = parser.parse_args()

    outcomes = []
    for model in args.models:
        outcomes.append((model, await run_model(model)))

    print("\n=== summary ===")
    for model, ok in outcomes:
        state = "PASS" if ok is True else "INCONCLUSIVE" if ok is None else "FAIL"
        print(f"{state}  {model}")
    if any(ok is False for _, ok in outcomes):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
