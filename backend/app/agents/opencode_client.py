import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.agents.errors import ResearchProviderError, ResearchProviderTimeoutError
from app.core.config import ROOT_DIR, Settings

logger = logging.getLogger(__name__)
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
ALLOWED_RESEARCH_TOOLS = {
    "websearch",
    "webfetch",
}


class OpenCodeError(ResearchProviderError):
    pass


class OpenCodeNotInstalledError(OpenCodeError):
    pass


class OpenCodeTimeoutError(OpenCodeError, ResearchProviderTimeoutError):
    def __init__(
        self,
        message: str,
        *,
        stdout: bytes = b"",
        stderr: bytes = b"",
        return_code: int | None = None,
    ):
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr
        self.return_code = return_code


class OpenCodeExecutionError(OpenCodeError):
    pass


@dataclass(frozen=True)
class OpenCodeRunArtifacts:
    stdout_path: Path
    stderr_path: Path
    metadata_path: Path


def extract_final_assistant_text(raw_stdout: str) -> str:
    """Extract the final assistant message from OpenCode 1.18.x JSONL events."""
    text_parts: list[tuple[str | None, str]] = []
    for line in raw_stdout.splitlines():
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(event, dict) or event.get("type") != "text":
            continue
        part = event.get("part")
        if not isinstance(part, dict) or part.get("type") != "text":
            continue
        content = part.get("text")
        if isinstance(content, str) and content:
            message_id = part.get("messageID")
            text_parts.append(
                (message_id if isinstance(message_id, str) else None, content)
            )

    if not text_parts:
        raise ValueError("OpenCode JSONL contained no assistant text event")

    final_message_id = text_parts[-1][0]
    if final_message_id is None:
        return "\n".join(content for _, content in text_parts).strip()
    return "\n".join(
        content for message_id, content in text_parts if message_id == final_message_id
    ).strip()


def extract_last_json_object(raw_stdout: str) -> str:
    """Return the last balanced, syntactically valid JSON object in text."""
    candidates: list[str] = []
    start: int | None = None
    depth = 0
    in_string = False
    escaped = False

    for index, character in enumerate(raw_stdout):
        if start is None:
            if character == "{":
                start = index
                depth = 1
                in_string = False
                escaped = False
            continue

        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue

        if character == '"':
            in_string = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                candidate = raw_stdout[start : index + 1]
                try:
                    parsed = json.loads(candidate)
                except json.JSONDecodeError:
                    pass
                else:
                    if isinstance(parsed, dict):
                        candidates.append(candidate)
                start = None

    if not candidates:
        raise ValueError("OpenCode output contained no valid JSON object")
    return candidates[-1]


def extract_tool_names(raw_stdout: str) -> list[str]:
    tools: list[str] = []

    for line in raw_stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        if not isinstance(event, dict) or event.get("type") != "tool_use":
            continue

        part = event.get("part")
        if not isinstance(part, dict):
            continue

        tool = part.get("tool")
        if isinstance(tool, str):
            tools.append(tool)

    return tools


class OpenCodeClient:
    def __init__(self, settings: Settings, working_directory: Path | None = None):
        self.command = (
            shutil.which(settings.opencode_command) or settings.opencode_command
        )
        self.agent = settings.opencode_agent
        self.timeout_seconds = settings.opencode_timeout_seconds
        self.model = settings.opencode_model
        self.server_url = settings.opencode_server_url
        self.working_directory = working_directory or ROOT_DIR
        self.artifact_directory = ROOT_DIR / "backend" / "logs" / "opencode"
        self.last_run_artifacts: OpenCodeRunArtifacts | None = None
        self.last_tools_used: list[str] = []
        self._version: str | None = None

    def _prepare_runtime_workspace(self, runtime_directory: Path) -> None:
        source_agent = ROOT_DIR / ".opencode" / "agents" / f"{self.agent}.md"

        if not source_agent.exists():
            raise OpenCodeExecutionError(
                f"OpenCode agent configuration was not found: {source_agent}"
            )

        target_agents = runtime_directory / ".opencode" / "agents"
        target_agents.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_agent, target_agents / source_agent.name)

    def _new_artifacts(self, vehicle_id: int | None) -> OpenCodeRunArtifacts:
        self.artifact_directory.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
        vehicle_label = str(vehicle_id) if vehicle_id is not None else "unknown"
        stem = f"vehicle_{vehicle_label}_{timestamp}"
        return OpenCodeRunArtifacts(
            stdout_path=self.artifact_directory / f"{stem}.stdout.jsonl",
            stderr_path=self.artifact_directory / f"{stem}.stderr.txt",
            metadata_path=self.artifact_directory / f"{stem}.meta.json",
        )

    def _save_artifacts(
        self,
        artifacts: OpenCodeRunArtifacts,
        *,
        vehicle_id: int | None,
        stdout: bytes,
        stderr: bytes,
        elapsed_seconds: float,
        return_code: int | None,
        runtime_prompt_chars: int,
        runtime_prompt_sha256: str,
    ) -> None:
        artifacts.stdout_path.write_bytes(stdout)
        artifacts.stderr_path.write_bytes(stderr)
        self.last_tools_used = extract_tool_names(
            stdout.decode("utf-8", errors="replace")
        )
        metadata = {
            "vehicle_id": vehicle_id,
            "agent": self.agent,
            "model": self.model,
            "runtime_prompt_chars": runtime_prompt_chars,
            "runtime_prompt_sha256": runtime_prompt_sha256,
            "elapsed_seconds": round(elapsed_seconds, 3),
            "return_code": return_code,
            "tools_used": self.last_tools_used,
        }
        artifacts.metadata_path.write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        logger.info("[OpenCode] Raw events saved: %s", artifacts.stdout_path)

    async def _create_process(
        self,
        *args: str,
        working_directory: Path | None = None,
        env: dict[str, str] | None = None,
    ):
        options: dict[str, object] = {}
        if os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            options["start_new_session"] = True
        try:
            return await asyncio.create_subprocess_exec(
                self.command,
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(working_directory or self.working_directory),
                env=env,
                **options,
            )
        except FileNotFoundError as exc:
            raise OpenCodeNotInstalledError(
                "OpenCode executable was not found. Install/configure OpenCode "
                "before using RESEARCH_PROVIDER=opencode."
            ) from exc

    @staticmethod
    def _safe_stderr(stderr: bytes, limit: int = 500) -> str:
        text = _ANSI_ESCAPE.sub("", stderr.decode("utf-8", errors="replace")).strip()
        if len(text) > limit:
            return text[:limit] + "..."
        return text

    async def _taskkill(self, pid: int, *, force: bool) -> None:
        args = ["taskkill", "/PID", str(pid), "/T"]
        if force:
            args.append("/F")
        try:
            killer = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(killer.wait(), timeout=3)
        except (FileNotFoundError, ProcessLookupError, TimeoutError):
            logger.warning("[OpenCode] Could not stop Windows process tree pid=%s", pid)

    async def _stop_process(self, process) -> None:
        if process.returncode is not None:
            return

        pid = getattr(process, "pid", None)
        if sys.platform == "win32" and isinstance(pid, int):
            await self._taskkill(pid, force=False)
        elif os.name != "nt" and isinstance(pid, int):
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except ProcessLookupError:
                return
        else:
            try:
                process.terminate()
            except ProcessLookupError:
                return

        try:
            await asyncio.wait_for(process.wait(), timeout=3)
            return
        except (TimeoutError, ProcessLookupError):
            pass

        if sys.platform == "win32" and isinstance(pid, int):
            await self._taskkill(pid, force=True)
        elif os.name != "nt" and isinstance(pid, int):
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
        elif process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass

        if process.returncode is None:
            try:
                await asyncio.wait_for(process.wait(), timeout=3)
            except (TimeoutError, ProcessLookupError):
                logger.warning(
                    "[OpenCode] Process did not report exit after forced stop"
                )

    async def _communicate(
        self, process, timeout_seconds: float
    ) -> tuple[bytes, bytes]:
        communication = asyncio.create_task(process.communicate())
        try:
            return await asyncio.wait_for(
                asyncio.shield(communication), timeout=timeout_seconds
            )
        except TimeoutError:
            await self._stop_process(process)
            stdout = b""
            stderr = b""
            try:
                stdout, stderr = await asyncio.wait_for(communication, timeout=3)
            except (
                TimeoutError,
                asyncio.CancelledError,
                ProcessLookupError,
                OSError,
            ) as exc:
                communication.cancel()
                logger.debug(
                    "[OpenCode] Could not collect output after timeout: %s", exc
                )
            timeout = f"{timeout_seconds:g}"
            raise OpenCodeTimeoutError(
                f"OpenCode research timed out after {timeout} seconds.",
                stdout=stdout,
                stderr=stderr,
                return_code=process.returncode,
            ) from None

    async def get_version(self) -> str:
        if self._version is not None:
            return self._version
        process = await self._create_process("--version")
        stdout, stderr = await self._communicate(process, min(self.timeout_seconds, 10))
        if process.returncode != 0:
            detail = self._safe_stderr(stderr) or "no error details"
            raise OpenCodeExecutionError(
                f"OpenCode version check failed (exit {process.returncode}): {detail}"
            )
        version = stdout.decode("utf-8", errors="replace").strip()
        if not version:
            raise OpenCodeExecutionError(
                "OpenCode version check returned empty output."
            )
        self._version = version
        return version

    async def run(self, prompt: str, *, vehicle_id: int | None = None) -> str:
        artifacts = self._new_artifacts(vehicle_id)
        self.last_run_artifacts = artifacts
        runtime_prompt_chars = len(prompt)
        runtime_prompt_sha256 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        logger.info("[OpenCode] Raw output will be saved to: %s", artifacts.stdout_path)
        overall_started = time.perf_counter()

        try:
            version = await self.get_version()
        except OpenCodeError as exc:
            self._save_artifacts(
                artifacts,
                vehicle_id=vehicle_id,
                stdout=getattr(exc, "stdout", b""),
                stderr=getattr(exc, "stderr", b""),
                elapsed_seconds=time.perf_counter() - overall_started,
                return_code=getattr(exc, "return_code", None),
                runtime_prompt_chars=runtime_prompt_chars,
                runtime_prompt_sha256=runtime_prompt_sha256,
            )
            raise

        logger.info(
            "[OpenCode] Starting research agent=%s version=%s", self.agent, version
        )
        with tempfile.TemporaryDirectory(
            prefix="snappcarfix-opencode-"
        ) as temporary_directory:
            runtime_directory = Path(temporary_directory).resolve()
            self._prepare_runtime_workspace(runtime_directory)
            runtime_request_path = runtime_directory / "runtime_request.md"
            runtime_request_path.write_text(
                prompt,
                encoding="utf-8",
                newline="",
            )
            logger.info("[OpenCode] Runtime request prepared")
            logger.info("[OpenCode] Runtime request chars: %s", runtime_prompt_chars)
            logger.info("[OpenCode] Runtime request attached via --file")
            logger.info("[OpenCode] Runtime workspace: isolated temporary directory")

            command = ["run", "--format", "json", "--agent", self.agent]
            if self.model:
                command.extend(["--model", self.model])
            if self.server_url:
                command.extend(["--attach", self.server_url])
            command.extend(["--file", str(runtime_request_path)])
            command.append(
                "Follow the attached runtime research request exactly. "
                "Use only websearch/webfetch as instructed and return the "
                "requested JSON object only."
            )

            child_env = os.environ.copy()
            child_env.pop("VIRTUAL_ENV", None)
            child_env.pop("PYTHONPATH", None)
            child_env.pop("OLDPWD", None)
            child_env["PWD"] = str(runtime_directory)

            startup_started = time.perf_counter()
            try:
                process = await self._create_process(
                    *command,
                    working_directory=runtime_directory,
                    env=child_env,
                )
            except OpenCodeError:
                self._save_artifacts(
                    artifacts,
                    vehicle_id=vehicle_id,
                    stdout=b"",
                    stderr=b"",
                    elapsed_seconds=time.perf_counter() - overall_started,
                    return_code=None,
                    runtime_prompt_chars=runtime_prompt_chars,
                    runtime_prompt_sha256=runtime_prompt_sha256,
                )
                raise
            logger.info(
                "[OpenCode] Process started in %.2fs",
                time.perf_counter() - startup_started,
            )

            research_started = time.perf_counter()
            try:
                stdout, stderr = await self._communicate(process, self.timeout_seconds)
            except OpenCodeTimeoutError as exc:
                self._save_artifacts(
                    artifacts,
                    vehicle_id=vehicle_id,
                    stdout=exc.stdout,
                    stderr=exc.stderr,
                    elapsed_seconds=time.perf_counter() - overall_started,
                    return_code=exc.return_code,
                    runtime_prompt_chars=runtime_prompt_chars,
                    runtime_prompt_sha256=runtime_prompt_sha256,
                )
                raise

            elapsed = time.perf_counter() - research_started
            self._save_artifacts(
                artifacts,
                vehicle_id=vehicle_id,
                stdout=stdout,
                stderr=stderr,
                elapsed_seconds=time.perf_counter() - overall_started,
                return_code=process.returncode,
                runtime_prompt_chars=runtime_prompt_chars,
                runtime_prompt_sha256=runtime_prompt_sha256,
            )
        logger.info("[OpenCode] Research completed in %.1fs", elapsed)

        raw_stdout = stdout.decode("utf-8", errors="replace")
        forbidden_tools = sorted(set(self.last_tools_used) - ALLOWED_RESEARCH_TOOLS)
        if forbidden_tools:
            raise OpenCodeExecutionError(
                "OpenCode research attempted forbidden local tools: "
                + ", ".join(forbidden_tools)
            )

        if process.returncode != 0:
            detail = self._safe_stderr(stderr) or "no error details"
            raise OpenCodeExecutionError(
                f"OpenCode exited with status {process.returncode}: {detail}"
            )

        if not raw_stdout.strip():
            raise OpenCodeExecutionError("OpenCode returned empty output.")

        extraction_started = time.perf_counter()
        try:
            final_content = extract_final_assistant_text(raw_stdout)
        except ValueError:
            try:
                final_content = extract_last_json_object(raw_stdout)
            except ValueError as exc:
                raise OpenCodeExecutionError(
                    "OpenCode output contained no extractable assistant response."
                ) from exc
            logger.warning("[OpenCode] Used last-JSON-object output fallback")
        logger.info(
            "[OpenCode] Final assistant content extracted: %s chars in %.3fs",
            len(final_content),
            time.perf_counter() - extraction_started,
        )
        return final_content
