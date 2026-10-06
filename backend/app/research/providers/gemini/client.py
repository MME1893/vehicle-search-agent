import asyncio
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from google import genai
from google.genai import errors, types
from pydantic import BaseModel

from app.core.config import Settings
from app.research.errors import (
    GeminiProviderError,
    ProviderAuthenticationError,
    ProviderQuotaError,
    ProviderRateLimitError,
    ResearchProviderConfigurationError,
    ResearchProviderTimeoutError,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GroundingSource:
    title: str | None
    uri: str | None


@dataclass(frozen=True)
class GroundingInfo:
    queries: list[str] = field(default_factory=list)
    sources: list[GroundingSource] = field(default_factory=list)
    chunk_count: int = 0

    @property
    def is_grounded(self) -> bool:
        return bool(self.queries or self.chunk_count)


class GeminiClient:
    def __init__(self, settings: Settings, client: Any | None = None):
        if not settings.gemini_api_key and client is None:
            raise ResearchProviderConfigurationError("GEMINI_API_KEY is required")
        if not settings.gemini_model:
            raise ResearchProviderConfigurationError("GEMINI_MODEL is required")
        self.client = client or genai.Client(api_key=settings.gemini_api_key)
        self._api_key = settings.gemini_api_key
        self.model = settings.gemini_model
        self.stage1_timeout_seconds = settings.gemini_stage1_timeout_seconds
        self.stage2_timeout_seconds = settings.gemini_stage2_timeout_seconds
        self.total_timeout_seconds = settings.gemini_total_timeout_seconds
        self.temperature = settings.gemini_temperature
        self.max_output_tokens = settings.gemini_max_output_tokens
        self.last_grounding = GroundingInfo()
        self.last_research_text: str | None = None
        self.last_structured_text: str | None = None
        self.last_grounded_duration: float | None = None
        self.last_extraction_duration: float | None = None

    @staticmethod
    def _grounding_info(response: Any) -> GroundingInfo:
        candidates = getattr(response, "candidates", None) or []
        metadata = (
            getattr(candidates[0], "grounding_metadata", None) if candidates else None
        )
        if metadata is None:
            return GroundingInfo()
        queries = [
            str(query)
            for query in (getattr(metadata, "web_search_queries", None) or [])
        ]
        chunks = getattr(metadata, "grounding_chunks", None) or []
        sources = []
        for chunk in chunks:
            web = getattr(chunk, "web", None)
            if web is not None:
                sources.append(
                    GroundingSource(
                        title=getattr(web, "title", None),
                        uri=getattr(web, "uri", None),
                    )
                )
        return GroundingInfo(
            queries=queries,
            sources=sources,
            chunk_count=len(chunks),
        )

    @asynccontextmanager
    async def research_budget(self):
        try:
            async with asyncio.timeout(self.total_timeout_seconds):
                yield
        except TimeoutError as exc:
            raise ResearchProviderTimeoutError(
                "Gemini research exceeded the total timeout of "
                f"{self.total_timeout_seconds:g} seconds"
            ) from exc

    @staticmethod
    def _is_overloaded(exc: errors.APIError) -> bool:
        status = str(getattr(exc, "status", "") or "").upper()
        message = str(getattr(exc, "message", "") or "").lower()
        return (
            getattr(exc, "code", None) == 503
            or status == "UNAVAILABLE"
            or "overload" in message
        )

    async def _generate(
        self,
        *,
        prompt: str,
        config: types.GenerateContentConfig,
        timeout_seconds: float,
        stage_name: str,
    ):
        try:
            async with asyncio.timeout(timeout_seconds):
                for attempt in range(2):
                    try:
                        return await self.client.aio.models.generate_content(
                            model=self.model,
                            contents=prompt,
                            config=config,
                        )
                    except errors.APIError as exc:
                        if attempt == 0 and self._is_overloaded(exc):
                            logger.warning(
                                "Gemini %s overloaded; retrying once", stage_name
                            )
                            await asyncio.sleep(0.5)
                            continue
                        code = getattr(exc, "code", None)
                        status = str(getattr(exc, "status", "") or "").upper()
                        if code == 401 or status in {"UNAUTHENTICATED", "PERMISSION_DENIED"}:
                            raise ProviderAuthenticationError(
                                "Gemini authentication failed"
                            ) from exc
                        if code == 402:
                            raise ProviderQuotaError("Gemini quota exhausted") from exc
                        if code == 429 or status == "RESOURCE_EXHAUSTED":
                            raise ProviderRateLimitError(
                                "Gemini rate limit or quota exceeded"
                            ) from exc
                        raise GeminiProviderError(
                            f"Gemini API request failed: {exc}"
                        ) from exc
        except TimeoutError as exc:
            raise ResearchProviderTimeoutError(
                f"Gemini {stage_name} timed out after {timeout_seconds:g} seconds"
            ) from exc
        except ResearchProviderTimeoutError:
            raise
        except (
            ProviderAuthenticationError,
            ProviderQuotaError,
            ProviderRateLimitError,
        ):
            raise
        except GeminiProviderError:
            raise
        except Exception as exc:
            detail = str(exc)
            if self._api_key:
                detail = detail.replace(self._api_key, "[REDACTED]")
            logger.error(
                "Gemini request failed: %s: %s",
                type(exc).__name__,
                detail,
            )
            raise GeminiProviderError(
                f"Gemini request failed: {type(exc).__name__}: {detail}"
            ) from exc

    async def generate_grounded(self, prompt: str):
        self.last_grounding = GroundingInfo()
        self.last_research_text = None
        self.last_structured_text = None
        self.last_grounded_duration = None
        self.last_extraction_duration = None
        started = time.perf_counter()
        try:
            response = await self._generate(
                prompt=prompt,
                config=types.GenerateContentConfig(
                    tools=[{"google_search": {}}],
                    temperature=self.temperature,
                    max_output_tokens=self.max_output_tokens,
                ),
                timeout_seconds=self.stage1_timeout_seconds,
                stage_name="Stage 1",
            )
        finally:
            self.last_grounded_duration = time.perf_counter() - started
        self.last_grounding = self._grounding_info(response)
        self.last_research_text = self.response_text(response)
        logger.info("[Gemini] Search queries: %s", len(self.last_grounding.queries))
        logger.info("[Gemini] Grounding chunks: %s", self.last_grounding.chunk_count)
        return response

    async def generate_structured(self, prompt: str, schema: type[BaseModel]) -> str:
        started = time.perf_counter()
        try:
            response = await self._generate(
                prompt=prompt,
                config=types.GenerateContentConfig(
                    temperature=0,
                    max_output_tokens=self.max_output_tokens,
                    response_mime_type="application/json",
                    response_schema=schema,
                ),
                timeout_seconds=self.stage2_timeout_seconds,
                stage_name="Stage 2",
            )
        finally:
            self.last_extraction_duration = time.perf_counter() - started
        self.last_structured_text = self.response_text(response)
        return self.last_structured_text

    @staticmethod
    def response_text(response: Any) -> str:
        try:
            content = response.text
        except Exception as exc:
            raise GeminiProviderError(
                "Gemini returned unreadable response text"
            ) from exc
        if not isinstance(content, str) or not content.strip():
            raise GeminiProviderError("Gemini returned empty response text")
        return content.strip()

    async def aclose(self) -> None:
        await self.client.aio.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        await self.aclose()
