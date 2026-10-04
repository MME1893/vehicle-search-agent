import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.errors import ResearchProviderError
from app.agents.gemini_client import GeminiClient
from app.agents.gemini_research_adapter import GeminiResearchAdapter
from app.core.config import get_settings
from app.models import Vehicle


def print_metrics(client: GeminiClient) -> None:
    if client.last_grounded_duration is not None:
        print(f"Stage 1 duration: {client.last_grounded_duration:.1f}s", flush=True)
    print("Search queries:", flush=True)
    for query in client.last_grounding.queries:
        print(f"- {query}", flush=True)
    print("Grounding sources:", flush=True)
    for source in client.last_grounding.sources:
        print(
            f"- {source.title or '(untitled)'}: {source.uri or '(no URI)'}", flush=True
        )
    if client.last_extraction_duration is not None:
        print(f"Stage 2 duration: {client.last_extraction_duration:.1f}s", flush=True)


async def main() -> int:
    settings = get_settings()
    if not settings.gemini_api_key:
        print("FAIL: GEMINI_API_KEY is required.", flush=True)
        return 1

    vehicle = Vehicle(
        id=312,
        manufacturer="Peugeot",
        model="206",
        trim="Type 5",
        production_year_from=2003,
        production_year_to=2021,
        engine_code="TU5",
        engine_displacement="1587",
        fuel_type="gasoline",
    )
    client = GeminiClient(settings)
    adapter = GeminiResearchAdapter(client)
    print(f"Model: {client.model}", flush=True)
    print("Google Search: enabled", flush=True)
    started = time.perf_counter()
    try:
        result = await adapter.research_vehicle_oil_spec(vehicle)
    except ResearchProviderError as exc:
        print_metrics(client)
        print(f"Pydantic: FAIL ({exc})", flush=True)
        return 1
    finally:
        await client.aclose()

    elapsed = time.perf_counter() - started
    print_metrics(client)
    print(f"Total duration: {elapsed:.1f}s", flush=True)
    print("Pydantic: PASS", flush=True)
    print(json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
