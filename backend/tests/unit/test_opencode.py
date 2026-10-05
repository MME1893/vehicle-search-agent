import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import Settings
from app.research.factory import create_research_agent
from app.research.providers.opencode.client import (
    ALLOWED_RESEARCH_TOOLS,
    OpenCodeClient,
    OpenCodeExecutionError,
    OpenCodeNotInstalledError,
    OpenCodeTimeoutError,
    extract_final_assistant_text,
    extract_last_json_object,
    extract_tool_names,
)
from app.research.providers.opencode.provider import (
    OpenCodeResearchProvider as OpenCodeResearchAgent,
)
from app.research.providers.openrouter.provider import (
    OpenRouterResearchProvider as ResearchAgent,
)
from app.research.providers.openrouter.provider import (
    ResearchExecutionError,
)

VALID_RESULT = b"""{
  "research_status": "FOUND",
  "vehicle_id": 312,
  "engine_code": "TU5",
  "recommended_sae": ["10W-40"],
  "alternative_sae": [],
  "minimum_api": "SL",
  "acea_specs": [],
  "oem_approvals": [],
  "confidence": 0.9,
  "sources": [{
    "title": "Manual",
    "url": "https://example.com/manual",
    "domain": "example.com",
    "source_type": "OFFICIAL_MANUAL",
    "supported_claims": ["SAE 10W-40"]
  }],
  "recommended_products": [],
  "notes": null
}"""


def settings(**values):
    defaults = {
        "research_provider": "opencode",
        "opencode_command": "opencode-test",
        "opencode_agent": "oil-research",
        "opencode_timeout_seconds": 12,
    }
    defaults.update(values)
    return Settings(**defaults)


@pytest.fixture(autouse=True)
def isolate_raw_output(monkeypatch, tmp_path):
    source_agent = (
        Path(__file__).resolve().parents[3]
        / ".opencode"
        / "agents"
        / "oil-research.md"
    )
    target_agent = tmp_path / ".opencode" / "agents" / "oil-research.md"
    target_agent.parent.mkdir(parents=True)
    target_agent.write_text(source_agent.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr("app.research.providers.opencode.client.ROOT_DIR", tmp_path)


def vehicle():
    return SimpleNamespace(
        id=312,
        manufacturer="Peugeot",
        model="206",
        trim="Type 5",
        production_year_from=2003,
        production_year_to=2021,
        engine_code="TU5",
        engine_displacement=1587,
        fuel_type="gasoline",
    )


def process(stdout=VALID_RESULT, stderr=b"", returncode=0):
    item = MagicMock()
    item.returncode = returncode
    item.communicate = AsyncMock(return_value=(stdout, stderr))
    item.wait = AsyncMock(return_value=returncode)
    return item


def jsonl_result(*tools: str) -> bytes:
    events = [
        {"type": "tool_use", "part": {"type": "tool", "tool": tool}}
        for tool in tools
    ]
    events.append(
        {
            "type": "text",
            "part": {
                "type": "text",
                "messageID": "msg_final",
                "text": VALID_RESULT.decode(),
            },
        }
    )
    return "\n".join(json.dumps(event) for event in events).encode()


def test_runtime_prompt_is_web_only_and_contains_exact_identity():
    persian_vehicle = SimpleNamespace(
        id=312,
        manufacturer="پژو",
        model="206",
        trim="تیپ 5",
        production_year_from=2003,
        production_year_to=2021,
        engine_code="TU5",
        engine_displacement=1587,
        fuel_type="gasoline",
    )
    prompt = OpenCodeResearchAgent.build_vehicle_prompt(persian_vehicle)

    assert "DO NOT inspect the local filesystem" in prompt
    assert "Use ONLY websearch" in prompt
    assert "Vehicle ID: 312" in prompt
    assert "Manufacturer: پژو" in prompt
    assert "Model: 206" in prompt
    assert "Trim / variant: تیپ 5" in prompt
    assert "Production years: 2003-2021" in prompt
    assert "Engine code: TU5" in prompt
    assert "Engine displacement: 1587" in prompt
    assert "Fuel type: gasoline" in prompt
    assert "vehicle_id MUST be exactly 312" in prompt
    assert 'engine_code MUST be exactly "TU5"' in prompt
    assert '"vehicle_id": 312' in prompt
    assert '"engine_code": "TU5"' in prompt
    assert '"recommended_sae": []' in prompt
    assert '"minimum_api": null' in prompt
    assert '"minimum_api_spec":' not in prompt
    assert '"vehicle": {' not in prompt
    assert '"vehicle_id": 123' not in prompt


@pytest.mark.asyncio
async def test_successful_run_parses_engine_oil_research_result(monkeypatch):
    item = process()
    spawn = AsyncMock(return_value=item)
    monkeypatch.setattr(
        "app.research.providers.opencode.client.asyncio.create_subprocess_exec", spawn
    )
    client = OpenCodeClient(settings(opencode_model="provider/model"))
    client._version = "1.18.34"

    result = await OpenCodeResearchAgent(client).research_vehicle_oil_spec(vehicle())

    assert result.vehicle_id == 312
    assert result.recommended_sae == ["10W-40"]
    args = spawn.await_args.args
    assert args[:8] == (
        "opencode-test",
        "run",
        "--format",
        "json",
        "--agent",
        "oil-research",
        "--model",
        "provider/model",
    )
    assert "Vehicle ID: 312" not in args
    assert args[-3] == "--file"
    assert Path(args[-2]).name == "runtime_request.md"
    assert len(args[-1]) < 200


@pytest.mark.asyncio
async def test_research_uses_minimal_isolated_working_directory(monkeypatch, tmp_path):
    observed = {}

    async def spawn_process(*args, **kwargs):
        runtime = Path(kwargs["cwd"])
        observed["cwd"] = runtime
        observed["files"] = sorted(
            path.relative_to(runtime).as_posix()
            for path in runtime.rglob("*")
            if path.is_file()
        )
        observed["agent"] = (
            runtime / ".opencode" / "agents" / "oil-research.md"
        ).read_text(encoding="utf-8")
        observed["env"] = kwargs["env"]
        observed["request"] = (runtime / "runtime_request.md").read_text(
            encoding="utf-8"
        )
        return process(stdout=jsonl_result("websearch"))

    monkeypatch.setattr(
        "app.research.providers.opencode.client.asyncio.create_subprocess_exec",
        AsyncMock(side_effect=spawn_process),
    )
    client = OpenCodeClient(settings())
    client._version = "1.18.34"

    await client.run("research", vehicle_id=312)

    assert observed["cwd"] != tmp_path
    assert observed["cwd"] != tmp_path / "backend"
    assert observed["files"] == [
        ".opencode/agents/oil-research.md",
        "runtime_request.md",
    ]
    assert observed["request"] == "research"
    assert "steps: 4" in observed["agent"]
    assert observed["env"]["PWD"] == str(observed["cwd"])
    assert "VIRTUAL_ENV" not in observed["env"]
    assert "PYTHONPATH" not in observed["env"]


@pytest.mark.asyncio
async def test_runtime_prompt_is_utf8_file_attachment_not_cli_argument(monkeypatch):
    prompt = (
        "Large multiline runtime request\n"
        "پژو 206\n"
        "تیپ 5\n"
        "TU5\n"
        + ("technical requirements\n" * 500)
    )
    observed = {}

    async def spawn_process(*args, **kwargs):
        runtime_request_path = Path(args[args.index("--file") + 1])
        observed["args"] = args
        observed["path"] = runtime_request_path
        observed["bytes"] = runtime_request_path.read_bytes()
        observed["text"] = runtime_request_path.read_text(encoding="utf-8")
        return process(stdout=jsonl_result("websearch"))

    monkeypatch.setattr(
        "app.research.providers.opencode.client.asyncio.create_subprocess_exec",
        AsyncMock(side_effect=spawn_process),
    )
    client = OpenCodeClient(settings())
    client._version = "1.18.34"

    await client.run(prompt, vehicle_id=312)

    assert prompt not in observed["args"]
    assert observed["path"].name == "runtime_request.md"
    assert observed["text"] == prompt
    assert observed["bytes"] == prompt.encode("utf-8")
    assert len(observed["args"][-1]) < 200
    assert observed["args"][-1].startswith(
        "Follow the attached runtime research request exactly."
    )
    metadata = json.loads(client.last_run_artifacts.metadata_path.read_text())
    assert metadata["runtime_prompt_chars"] == len(prompt)
    assert len(metadata["runtime_prompt_sha256"]) == 64


@pytest.mark.asyncio
async def test_executable_not_installed_is_clear_domain_error(monkeypatch):
    spawn = AsyncMock(side_effect=FileNotFoundError)
    monkeypatch.setattr(
        "app.research.providers.opencode.client.asyncio.create_subprocess_exec", spawn
    )
    with pytest.raises(OpenCodeNotInstalledError, match="executable was not found"):
        await OpenCodeClient(settings()).run("research")


@pytest.mark.asyncio
async def test_timeout_terminates_process(monkeypatch):
    item = process()
    item.returncode = None
    item.communicate = AsyncMock(side_effect=TimeoutError)

    def terminate():
        item.returncode = -15

    item.terminate.side_effect = terminate
    spawn = AsyncMock(return_value=item)
    monkeypatch.setattr(
        "app.research.providers.opencode.client.asyncio.create_subprocess_exec", spawn
    )
    client = OpenCodeClient(settings())
    client._version = "1.18.34"

    with pytest.raises(OpenCodeTimeoutError, match="timed out after 12 seconds"):
        await client.run("research")
    item.terminate.assert_called_once()
    item.wait.assert_awaited_once()


@pytest.mark.asyncio
async def test_one_second_timeout_stops_process_and_saves_output(monkeypatch):
    item = process()
    item.returncode = None

    async def hang():
        await asyncio.Event().wait()

    item.communicate = AsyncMock(side_effect=hang)

    def terminate():
        item.returncode = -15

    item.terminate.side_effect = terminate
    monkeypatch.setattr(
        "app.research.providers.opencode.client.asyncio.create_subprocess_exec",
        AsyncMock(return_value=item),
    )
    client = OpenCodeClient(settings(opencode_timeout_seconds=1))
    client._version = "1.18.34"

    with pytest.raises(OpenCodeTimeoutError, match="timed out after 1 seconds"):
        await client.run("research", vehicle_id=312)

    item.terminate.assert_called_once()
    assert client.last_run_artifacts is not None
    assert client.last_run_artifacts.stdout_path.exists()
    assert client.last_run_artifacts.stderr_path.exists()


@pytest.mark.asyncio
async def test_nonzero_exit_includes_safe_stderr(monkeypatch):
    spawn = AsyncMock(return_value=process(stderr=b"provider failed", returncode=1))
    monkeypatch.setattr(
        "app.research.providers.opencode.client.asyncio.create_subprocess_exec", spawn
    )
    client = OpenCodeClient(settings())
    client._version = "1.18.34"
    with pytest.raises(OpenCodeExecutionError, match="provider failed"):
        await client.run("research")


@pytest.mark.asyncio
async def test_empty_output_is_rejected(monkeypatch):
    spawn = AsyncMock(return_value=process(stdout=b""))
    monkeypatch.setattr(
        "app.research.providers.opencode.client.asyncio.create_subprocess_exec", spawn
    )
    client = OpenCodeClient(settings())
    client._version = "1.18.34"
    with pytest.raises(OpenCodeExecutionError, match="empty output"):
        await client.run("research")


@pytest.mark.parametrize("forbidden_tool", ["grep", "read", "bash"])
@pytest.mark.asyncio
async def test_forbidden_local_tool_event_is_rejected(monkeypatch, forbidden_tool):
    monkeypatch.setattr(
        "app.research.providers.opencode.client.asyncio.create_subprocess_exec",
        AsyncMock(return_value=process(stdout=jsonl_result(forbidden_tool))),
    )
    client = OpenCodeClient(settings())
    client._version = "1.18.34"

    with pytest.raises(OpenCodeExecutionError, match=forbidden_tool):
        await client.run("research", vehicle_id=312)

    metadata = json.loads(client.last_run_artifacts.metadata_path.read_text())
    assert metadata["tools_used"] == [forbidden_tool]


@pytest.mark.asyncio
async def test_valid_web_only_tool_stream_is_accepted(monkeypatch):
    tools = ("websearch", "websearch", "webfetch")
    monkeypatch.setattr(
        "app.research.providers.opencode.client.asyncio.create_subprocess_exec",
        AsyncMock(return_value=process(stdout=jsonl_result(*tools))),
    )
    client = OpenCodeClient(settings())
    client._version = "1.18.34"

    result = await client.run("research", vehicle_id=312)

    assert json.loads(result)["vehicle_id"] == 312
    assert client.last_tools_used == list(tools)
    assert ALLOWED_RESEARCH_TOOLS == {"websearch", "webfetch"}


@pytest.mark.asyncio
async def test_empty_tool_list_may_pass(monkeypatch):
    monkeypatch.setattr(
        "app.research.providers.opencode.client.asyncio.create_subprocess_exec",
        AsyncMock(return_value=process()),
    )
    client = OpenCodeClient(settings())
    client._version = "1.18.34"

    assert json.loads(await client.run("research"))["vehicle_id"] == 312
    assert client.last_tools_used == []


def test_extract_tool_names_ignores_non_tool_events():
    raw = jsonl_result("websearch", "webfetch").decode()

    assert extract_tool_names(raw) == ["websearch", "webfetch"]


@pytest.mark.asyncio
async def test_invalid_json_fails_without_second_research_run():
    client = SimpleNamespace(run=AsyncMock(return_value="not json"))
    with pytest.raises(ResearchExecutionError, match="invalid research JSON"):
        await OpenCodeResearchAgent(client).research_vehicle_oil_spec(vehicle())
    client.run.assert_awaited_once()


def test_extracts_only_final_assistant_message_after_tool_events():
    expected = VALID_RESULT.decode()
    final_first, final_rest = expected.split("\n", 1)
    events = [
        {"type": "tool_use", "part": {"type": "tool", "tool": "websearch"}},
        {
            "type": "text",
            "part": {
                "type": "text",
                "messageID": "msg_intermediate",
                "text": "I found a likely manual.",
            },
        },
        {"type": "tool_use", "part": {"type": "tool", "tool": "webfetch"}},
        {
            "type": "text",
            "part": {
                "type": "text",
                "messageID": "msg_final",
                "text": final_first,
            },
        },
        {
            "type": "text",
            "part": {
                "type": "text",
                "messageID": "msg_final",
                "text": final_rest,
            },
        },
    ]
    raw = "\n".join(json.dumps(event) for event in events)

    assert extract_final_assistant_text(raw) == expected


def test_extracts_last_balanced_json_object_fallback():
    raw = (
        'some log line\nanother log line\n{"ignored": true}\n'
        '{"research_status": "FOUND"}'
    )

    assert json.loads(extract_last_json_object(raw)) == {"research_status": "FOUND"}


@pytest.mark.asyncio
async def test_raw_output_exists_before_research_parser_runs(monkeypatch):
    expected = VALID_RESULT.decode()
    raw_events = "\n".join(
        json.dumps(event)
        for event in [
            {
                "type": "tool_use",
                "part": {"type": "tool", "tool": "websearch"},
            },
            {
                "type": "text",
                "part": {
                    "type": "text",
                    "messageID": "msg_final",
                    "text": expected,
                },
            },
        ]
    ).encode()
    item = process(stdout=raw_events)
    monkeypatch.setattr(
        "app.research.providers.opencode.client.asyncio.create_subprocess_exec",
        AsyncMock(return_value=item),
    )
    client = OpenCodeClient(settings())
    client._version = "1.18.34"

    from app.research.parser import parse_research_result as real_parser

    def parser_spy(content):
        assert client.last_run_artifacts is not None
        assert client.last_run_artifacts.stdout_path.read_bytes() == raw_events
        assert content == expected
        return real_parser(content)

    monkeypatch.setattr(
        "app.research.providers.opencode.provider.parse_research_result", parser_spy
    )
    result = await OpenCodeResearchAgent(client).research_vehicle_oil_spec(vehicle())

    assert result.vehicle_id == 312


@pytest.mark.asyncio
async def test_mismatched_vehicle_identity_is_rejected():
    mismatched = json.loads(VALID_RESULT)
    mismatched["vehicle_id"] = 123
    client = SimpleNamespace(run=AsyncMock(return_value=json.dumps(mismatched)))

    with pytest.raises(ResearchExecutionError, match="vehicle_id"):
        await OpenCodeResearchAgent(client).research_vehicle_oil_spec(vehicle())


def test_provider_selection_keeps_both_implementations():
    assert isinstance(create_research_agent(settings()), OpenCodeResearchAgent)
    openrouter = create_research_agent(
        Settings(
            research_provider="openrouter",
            openrouter_api_key="test-key",
            openrouter_model="provider/model",
        )
    )
    assert isinstance(openrouter, ResearchAgent)


def test_command_is_resolved_from_path_for_windows_npm_shim(monkeypatch):
    monkeypatch.setattr(
        "app.research.providers.opencode.client.shutil.which",
        lambda command: "C:/npm/opencode.CMD",
    )
    assert OpenCodeClient(settings()).command == "C:/npm/opencode.CMD"
