"""Live developer smoke test. This file is intentionally not part of pytest."""

import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.research.providers.opencode.client import OpenCodeClient, OpenCodeError
from app.research.providers.opencode.provider import OpenCodeResearchProvider
from app.research.providers.openrouter.provider import ResearchExecutionError


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    client = OpenCodeClient(settings)
    agent = OpenCodeResearchProvider(client)
    vehicle = SimpleNamespace(
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

    print("Checking OpenCode...", flush=True)
    print(f"OpenCode version: {await client.get_version()}", flush=True)
    print(f"\nAgent: {client.agent}", flush=True)
    print("Research runtime: isolated", flush=True)
    print("Allowed tools: websearch, webfetch", flush=True)
    print("Maximum agent steps: 4", flush=True)
    print("\nResearching:\nPeugeot 206 Type 5\nTU5 / 1587 cc", flush=True)
    print("\nStarting OpenCode...\nSearching web...", flush=True)
    started = time.perf_counter()
    research_task = asyncio.create_task(agent.research_vehicle_oil_spec(vehicle))
    await asyncio.sleep(0)
    if client.last_run_artifacts:
        raw_path = client.last_run_artifacts.stdout_path
        try:
            raw_path = raw_path.relative_to(Path(__file__).resolve().parents[2])
        except ValueError:
            pass
        print(f"Raw output will be saved to:\n{raw_path}\n", flush=True)

    try:
        result = await research_task
    except ResearchExecutionError:
        print("\nResearch JSON parsing FAILED.", flush=True)
        if client.last_run_artifacts:
            print(
                f"\nInspect raw output:\n{client.last_run_artifacts.stdout_path}",
                flush=True,
            )
        raise

    print(f"\nResearch completed in {time.perf_counter() - started:.1f}s", flush=True)
    print("\nTools used:", flush=True)
    for tool in client.last_tools_used:
        print(f"- {tool}", flush=True)
    if not client.last_tools_used:
        print("- none", flush=True)
    print("\nFinal assistant response extracted.", flush=True)
    print(f"\nStatus: {result.research_status.value}", flush=True)
    print(f"SAE: {', '.join(result.recommended_sae) or '-'}", flush=True)
    print(f"API: {result.minimum_api or '-'}", flush=True)
    print("\nSources:", flush=True)
    for source in result.sources:
        print(f"- {source.title}: {source.url}", flush=True)
    print("\nPydantic validation: PASS", flush=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (OpenCodeError, ResearchExecutionError) as exc:
        detail = str(exc)
        prefix = "OpenCode research attempted forbidden local tools: "
        if detail.startswith(prefix):
            forbidden = detail.removeprefix(prefix).split(", ", 1)[0]
            detail = f"Research agent attempted a forbidden local tool: {forbidden}"
        print(f"\nERROR:\n{detail}", flush=True)
        raise SystemExit(1) from None
