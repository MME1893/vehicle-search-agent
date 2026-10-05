import logging
import time
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    RateLimitError,
)

from app.core.config import Settings
from app.research.errors import (
    ResearchProviderConfigurationError,
    ResearchProviderError,
    ResearchProviderTimeoutError,
)

logger = logging.getLogger(__name__)


class OpenRouterConfigurationError(ResearchProviderConfigurationError):
    pass


class OpenRouterProviderError(ResearchProviderError):
    pass


class OpenRouterTimeoutError(OpenRouterProviderError, ResearchProviderTimeoutError):
    pass


class OpenRouterClient:
    def __init__(self, settings: Settings, client: AsyncOpenAI | None = None):
        if not settings.openrouter_api_key:
            raise OpenRouterConfigurationError("OPENROUTER_API_KEY is required")
        if not settings.openrouter_model:
            raise OpenRouterConfigurationError("OPENROUTER_MODEL is required")
        headers = {"X-Title": settings.openrouter_app_name}
        if settings.openrouter_app_url:
            headers["HTTP-Referer"] = settings.openrouter_app_url
        self.client = client or AsyncOpenAI(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
            timeout=settings.openrouter_timeout_seconds,
            max_retries=settings.openrouter_max_retries,
            default_headers=headers,
        )
        self.model = settings.openrouter_model
        self.timeout_seconds = settings.openrouter_timeout_seconds

    async def aclose(self) -> None:
        await self.client.close()

    async def create_completion(
        self,
        *,
        messages: list[dict[str, str]],
        tools: list[dict[str, str]] | None = None,
    ) -> Any:
        request: dict[str, Any] = {"model": self.model, "messages": messages}
        if tools is not None:
            request["tools"] = tools
        web_search = bool(
            tools and any(tool.get("type") == "openrouter:web_search" for tool in tools)
        )
        logger.info(
            "OpenRouter request started model=%s web_search=%s",
            self.model,
            str(web_search).lower(),
        )
        started = time.perf_counter()
        try:
            response = await self.client.chat.completions.create(**request)
        except AuthenticationError as exc:
            raise OpenRouterProviderError("OpenRouter authentication failed") from exc
        except APITimeoutError as exc:
            timeout = f"{self.timeout_seconds:g}"
            raise OpenRouterTimeoutError(
                f"OpenRouter request timed out after {timeout} seconds"
            ) from exc
        except RateLimitError as exc:
            raise OpenRouterProviderError("OpenRouter rate limit exceeded") from exc
        except APIConnectionError as exc:
            raise OpenRouterProviderError("OpenRouter connection failed") from exc
        except APIStatusError as exc:
            raise OpenRouterProviderError(
                f"OpenRouter returned HTTP {exc.status_code}"
            ) from exc
        elapsed = time.perf_counter() - started
        logger.info("OpenRouter request completed elapsed=%.1fs", elapsed)
        return response
