"""Live OpenCode free-model diagnostic + research smoke test.

For each model the script first runs a tiny headless preflight with the default
OpenCode agent. Only models that pass the preflight proceed to the real
vehicle-research agent. This separates free-tier/upstream/headless failures
from failures caused by the research prompt or web tools.

Debug logs are enabled for the production research run and written to the
normal OpenCode stderr artifact.
"""

import argparse
import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.research.providers.opencode.client import (
    OpenCodeClient,
    OpenCodeTimeoutError,
    extract_final_assistant_text,
)
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


def _tail(data: bytes, limit: int = 1600) -> str:
    text = data.decode("utf-8", errors="replace").strip()
    return text[-limit:] if len(text) > limit else text


async def preflight_model(
    client: OpenCodeClient,
    model: str,
    timeout_seconds: float,
) -> bool:
    """Verify the free model can answer a trivial headless request at all."""
    runtime_directory = Path(
        tempfile.mkdtemp(prefix="snappcarfix-opencode-preflight-")
    ).resolve()
    child_env = os.environ.copy()
    child_env.pop("VIRTUAL_ENV", None)
    child_env.pop("PYTHONPATH", None)
    child_env.pop("OLDPWD", None)
    child_env["PWD"] = str(runtime_directory)

    command = [
        "--print-logs",
        "--log-level",
        "DEBUG",
        "run",
        "--format",
        "json",
        "--model",
        model,
        "Reply with exactly OK. Do not use any tools.",
    ]

    started = time.perf_counter()
    process = None
    stdout = b""
    stderr = b""
    try:
        process = await client._create_process(  # diagnostic script, intentional
            *command,
            working_directory=runtime_directory,
            env=child_env,
        )
        stdout, stderr = await client._communicate(  # diagnostic script, intentional
            process, timeout_seconds
        )
    except OpenCodeTimeoutError as exc:
        stdout, stderr = exc.stdout, exc.stderr
        print(
            f"preflight: TIMEOUT ({time.perf_counter() - started:.1f}s)",
            flush=True,
        )
        if stderr:
            print("preflight debug tail:\n" + _tail(stderr), flush=True)
        return False
    except Exception as exc:  # noqa: BLE001 - live diagnostic boundary
        print(
            f"preflight: FAIL ({time.perf_counter() - started:.1f}s): {exc}",
            flush=True,
        )
        if stderr:
            print("preflight debug tail:\n" + _tail(stderr), flush=True)
        return False
    finally:
        await client._cleanup_runtime_directory(runtime_directory)

    if process is None or process.returncode != 0:
        print(
            f"preflight: FAIL ({time.perf_counter() - started:.1f}s) "
            f"exit={getattr(process, 'returncode', None)}",
            flush=True,
        )
        if stderr:
            print("preflight debug tail:\n" + _tail(stderr), flush=True)
        return False

    try:
        answer = extract_final_assistant_text(stdout.decode("utf-8", errors="replace"))
    except ValueError:
        answer = ""

    if answer.strip().upper() != "OK":
        print(
            f"preflight: FAIL ({time.perf_counter() - started:.1f}s) "
            f"unexpected answer={answer!r}",
            flush=True,
        )
        if stderr:
            print("preflight debug tail:\n" + _tail(stderr), flush=True)
        return False

    print(f"preflight: PASS ({time.perf_counter() - started:.1f}s)", flush=True)
    return True


async def run_model(
    model: str,
    *,
    preflight_timeout: float,
    research_timeout: float,
) -> bool:
    base = get_settings()
    settings = base.model_copy(
        update={
            "opencode_model": model,
            "opencode_timeout_seconds": research_timeout,
            "opencode_debug_logs": True,
        }
    )
    client = OpenCodeClient(settings)
    provider = OpenCodeResearchProvider(client)

    print(f"\n=== {model} ===", flush=True)
    try:
        version = await client.get_version()
        print(f"opencode version: {version}", flush=True)
    except Exception as exc:  # noqa: BLE001 - live diagnostic boundary
        print(f"version check: FAIL: {exc}", flush=True)
        return False

    if not await preflight_model(client, model, preflight_timeout):
        print("research: SKIPPED because preflight failed", flush=True)
        return False

    started = time.perf_counter()
    try:
        execution = await provider.research_vehicle_oil_spec(vehicle())
    except Exception as exc:  # noqa: BLE001 - live diagnostic boundary
        print(f"research: FAIL ({time.perf_counter() - started:.1f}s): {exc}", flush=True)
        if client.last_tools_used:
            print("tools attempted: " + ", ".join(client.last_tools_used))
        if client.last_run_artifacts:
            print(f"stdout: {client.last_run_artifacts.stdout_path}")
            print(f"debug:  {client.last_run_artifacts.stderr_path}")
            try:
                debug_tail = _tail(client.last_run_artifacts.stderr_path.read_bytes())
            except OSError:
                debug_tail = ""
            if debug_tail:
                print("debug tail:\n" + debug_tail)
        return False
    finally:
        await provider.aclose()

    result = execution.research
    print(f"research: PASS ({time.perf_counter() - started:.1f}s)", flush=True)
    print("tools used: " + (", ".join(client.last_tools_used) or "none"))
    print(f"status: {result.research_status.value}")
    print(f"SAE: {', '.join(result.recommended_sae) or '-'}")
    print(f"API: {result.minimum_api or '-'}")
    print(f"sources: {len(result.sources)}")
    if client.last_run_artifacts:
        print(f"stdout: {client.last_run_artifacts.stdout_path}")
        print(f"debug:  {client.last_run_artifacts.stderr_path}")
    return True


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("models", nargs="*", default=list(DEFAULT_MODELS))
    parser.add_argument("--preflight-timeout", type=float, default=45.0)
    parser.add_argument("--research-timeout", type=float, default=180.0)
    args = parser.parse_args()

    outcomes = []
    for model in args.models:
        outcomes.append(
            (
                model,
                await run_model(
                    model,
                    preflight_timeout=args.preflight_timeout,
                    research_timeout=args.research_timeout,
                ),
            )
        )

    print("\n=== summary ===")
    for model, ok in outcomes:
        print(f"{'PASS' if ok else 'FAIL'}  {model}")
    if not all(ok for _, ok in outcomes):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
