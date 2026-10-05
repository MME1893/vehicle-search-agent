"""Live OpenCode free-model smoke test against the real research agent.

The script reuses the production isolated temp workspace + file-attached prompt
and prints which tools each model attempted. It is intentionally manual and is
not part of pytest.
"""

import argparse
import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.research.providers.opencode.client import OpenCodeClient
from app.research.providers.opencode.provider import OpenCodeResearchProvider

DEFAULT_MODELS = (
    "opencode/mimo-v2.6-flash-free",
    "opencode/nemotron-3.5-lightning-free",
    "opencode/big-pickle",
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


async def run_model(model: str) -> bool:
    base = get_settings()
    settings = base.model_copy(update={"opencode_model": model})
    client = OpenCodeClient(settings)
    provider = OpenCodeResearchProvider(client)
    started = time.perf_counter()
    print(f"\n=== {model} ===", flush=True)
    try:
        execution = await provider.research_vehicle_oil_spec(vehicle())
    except Exception as exc:  # live diagnostic script: preserve exact failure
        print(f"FAIL ({time.perf_counter() - started:.1f}s): {exc}", flush=True)
        if client.last_tools_used:
            print("tools attempted: " + ", ".join(client.last_tools_used))
        if client.last_run_artifacts:
            print(f"raw: {client.last_run_artifacts.stdout_path}")
        return False
    finally:
        await provider.aclose()

    result = execution.research
    print(f"PASS ({time.perf_counter() - started:.1f}s)", flush=True)
    print("tools used: " + (", ".join(client.last_tools_used) or "none"))
    print(f"status: {result.research_status.value}")
    print(f"SAE: {', '.join(result.recommended_sae) or '-'}")
    print(f"API: {result.minimum_api or '-'}")
    print(f"sources: {len(result.sources)}")
    if client.last_run_artifacts:
        print(f"raw: {client.last_run_artifacts.stdout_path}")
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
        print(f"{'PASS' if ok else 'FAIL'}  {model}")
    if not all(ok for _, ok in outcomes):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
