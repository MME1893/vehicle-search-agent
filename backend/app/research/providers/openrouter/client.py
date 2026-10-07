import logging
import time
from typing import Any, NoReturn

import httpx2
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    DefaultAsyncHttpx2Client,
    RateLimitError,
)

from app.core.config import Settings
from app.research.errors import (
    ProviderAuthenticationError,
    ProviderExecutionError,
    ProviderQuotaError,
    ProviderRateLimitError,
    ResearchProviderConfigurationError,
    ResearchProviderTimeoutError,
)
from app.research.proxy.resin import ResinControlError, ResinProxyManager

logger = logging.getLogger(__name__)


class OpenRouterConfigurationError(ResearchProviderConfigurationError):
    pass


class OpenRouterProviderError(ProviderExecutionError):
    pass


class OpenRouterTimeoutError(OpenRouterProviderError, ResearchProviderTimeoutError):
    pass


class OpenRouterClient:
    def __init__(
        self,
        settings: Settings,
        client: AsyncOpenAI | None = None,
        proxy_manager: ResinProxyManager | None = None,
    ):
        if not settings.openrouter_api_key:
            raise OpenRouterConfigurationError("OPENROUTER_API_KEY is required")
        if not settings.openrouter_model:
            raise OpenRouterConfigurationError("OPENROUTER_MODEL is required")
        headers = {"X-Title": settings.openrouter_app_name}
        if settings.openrouter_app_url:
            headers["HTTP-Referer"] = settings.openrouter_app_url
        self._owns_client = client is None
        self._owns_proxy_manager = proxy_manager is None and settings.resin_enabled
        self.proxy_manager = proxy_manager
        if settings.resin_enabled and self.proxy_manager is None:
            self.proxy_manager = ResinProxyManager(settings)
        self._client_kwargs: dict[str, Any] = {
            "api_key": settings.openrouter_api_key,
            "base_url": settings.openrouter_base_url,
            "timeout": settings.openrouter_timeout_seconds,
            "max_retries": 0,
            "default_headers": headers,
        }
        if client is None:
            self.client = self._new_client()
        else:
            self.client = client
        self.model = settings.openrouter_model
        self.timeout_seconds = settings.openrouter_timeout_seconds

    async def aclose(self) -> None:
        try:
            if self._owns_client:
                await self.client.close()
        finally:
            if self.proxy_manager is not None and self._owns_proxy_manager:
                await self.proxy_manager.aclose()

    def _new_client(self) -> AsyncOpenAI:
        client_kwargs = dict(self._client_kwargs)
        if self.proxy_manager is not None:
            client_kwargs["http_client"] = DefaultAsyncHttpx2Client(
                proxy=self.proxy_manager.proxy_url
            )
        return AsyncOpenAI(**client_kwargs)

    async def _close_owned_client(self) -> None:
        if not self._owns_client:
            return
        await self.client.close()

    def _replace_owned_client(self) -> None:
        if self._owns_client:
            self.client = self._new_client()

    @staticmethod
    def _is_connect_timeout(exc: APITimeoutError) -> bool:
        cause = exc.__cause__
        seen: set[int] = set()
        while cause is not None and id(cause) not in seen:
            if isinstance(cause, httpx2.ConnectTimeout):
                return True
            if isinstance(cause, httpx2.ReadTimeout):
                return False
            seen.add(id(cause))
            cause = cause.__cause__ or cause.__context__
        return False

    @classmethod
    def _is_network_failover_error(cls, exc: Exception) -> bool:
        if isinstance(exc, APITimeoutError):
            return cls._is_connect_timeout(exc)
        return isinstance(exc, APIConnectionError)

    @staticmethod
    def _is_rate_limit_status(exc: Exception) -> bool:
        return isinstance(exc, APIStatusError) and exc.status_code == 429

    @staticmethod
    def _is_other_http_failover_status(exc: Exception) -> bool:
        return isinstance(exc, APIStatusError) and exc.status_code == 403

    async def _failover_through_resin(self, exc: Exception) -> None:
        assert self.proxy_manager is not None
        await self._close_owned_client()
        try:
            await self.proxy_manager.reset_route()
            remaining = await self.proxy_manager.routable_node_count()
        except ResinControlError:
            logger.warning(
                "Resin failover control failed platform=%s account=%s",
                self.proxy_manager.platform,
                self.proxy_manager.account,
            )
            self._raise_mapped_error(exc)
        logger.info(
            "Resin routable routes remaining platform=%s account=%s "
            "routable_node_count=%d",
            self.proxy_manager.platform,
            self.proxy_manager.account,
            remaining,
        )
        if remaining == 0:
            self._raise_mapped_error(exc)
        self._replace_owned_client()

    async def _rotate_after_rate_limit(
        self,
        exc: APIStatusError,
        candidate_egress_ips: set[str] | None,
        attempted_egress_ips: set[str],
        rotation_count: int,
        rotation_budget: int | None,
    ) -> tuple[set[str], int, int]:
        assert self.proxy_manager is not None
        try:
            if candidate_egress_ips is None:
                pool = await self.proxy_manager.routable_egress_pool()
                candidate_egress_ips = set(pool.egress_ips)
                rotation_budget = max(1, len(candidate_egress_ips) * 2)
                logger.info(
                    "Resin 429 egress snapshot platform=%s account=%s "
                    "candidate_egress_count=%d routable_node_count=%d "
                    "rotation_budget=%d",
                    self.proxy_manager.platform,
                    self.proxy_manager.account,
                    len(candidate_egress_ips),
                    pool.node_count,
                    rotation_budget,
                )
                if not candidate_egress_ips:
                    self._raise_mapped_error(exc)

            assert rotation_budget is not None
            lease = await self.proxy_manager.current_lease()
            observed_egress_ip = None
            if (
                lease is not None
                and isinstance(lease.egress_ip, str)
                and lease.egress_ip
            ):
                observed_egress_ip = lease.egress_ip.strip()
                if observed_egress_ip:
                    attempted_egress_ips.add(observed_egress_ip)
                    if observed_egress_ip not in candidate_egress_ips:
                        logger.info(
                            "OpenRouter 429 Resin egress outside initial snapshot "
                            "model=%s account=%s egress_ip=%s",
                            self.model,
                            self.proxy_manager.account,
                            observed_egress_ip,
                        )
            logger.info(
                "OpenRouter 429 observed on Resin egress model=%s account=%s "
                "egress_ip=%s node_hash=%s attempted_egress_count=%d "
                "candidate_egress_count=%d rotation_count=%d rotation_budget=%d",
                self.model,
                self.proxy_manager.account,
                observed_egress_ip,
                lease.node_hash if lease else None,
                len(attempted_egress_ips),
                len(candidate_egress_ips),
                rotation_count,
                rotation_budget,
            )

            if candidate_egress_ips.issubset(attempted_egress_ips):
                logger.warning(
                    "OpenRouter 429 exhausted Resin egress snapshot "
                    "attempted_egress_count=%d candidate_egress_count=%d",
                    len(attempted_egress_ips),
                    len(candidate_egress_ips),
                )
                self._raise_mapped_error(exc)
            if rotation_count >= rotation_budget:
                logger.warning(
                    "OpenRouter 429 Resin rotation budget exhausted "
                    "rotation_count=%d rotation_budget=%d "
                    "attempted_egress_count=%d candidate_egress_count=%d",
                    rotation_count,
                    rotation_budget,
                    len(attempted_egress_ips),
                    len(candidate_egress_ips),
                )
                self._raise_mapped_error(exc)

            await self._close_owned_client()
            await self.proxy_manager.reset_route()
        except ResinControlError:
            logger.warning(
                "Resin 429 control failed platform=%s account=%s",
                self.proxy_manager.platform,
                self.proxy_manager.account,
            )
            self._raise_mapped_error(exc)

        rotation_count += 1
        self._replace_owned_client()
        return candidate_egress_ips, rotation_count, rotation_budget

    def _raise_mapped_error(self, exc: Exception) -> NoReturn:
        if isinstance(exc, AuthenticationError):
            raise ProviderAuthenticationError("OpenRouter authentication failed") from exc
        if isinstance(exc, APITimeoutError):
            if self._is_connect_timeout(exc):
                raise OpenRouterProviderError("OpenRouter connection failed") from exc
            timeout = f"{self.timeout_seconds:g}"
            raise OpenRouterTimeoutError(
                f"OpenRouter request timed out after {timeout} seconds"
            ) from exc
        if isinstance(exc, RateLimitError):
            raise ProviderRateLimitError("OpenRouter rate limit exceeded") from exc
        if isinstance(exc, APIConnectionError):
            raise OpenRouterProviderError("OpenRouter connection failed") from exc
        if isinstance(exc, APIStatusError):
            if exc.status_code == 401:
                raise ProviderAuthenticationError(
                    "OpenRouter authentication failed"
                ) from exc
            if exc.status_code == 402:
                raise ProviderQuotaError("OpenRouter credit quota exhausted") from exc
            if exc.status_code == 429:
                raise ProviderRateLimitError("OpenRouter rate limit exceeded") from exc
            raise OpenRouterProviderError(
                f"OpenRouter returned HTTP {exc.status_code}"
            ) from exc
        raise exc

    async def create_completion(
        self,
        *,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
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
        attempt = 1
        candidate_egress_ips: set[str] | None = None
        attempted_egress_ips: set[str] = set()
        rotation_count = 0
        rotation_budget: int | None = None
        while True:
            try:
                response = await self.client.chat.completions.create(**request)
                break
            except (APIConnectionError, APIStatusError) as exc:
                if self.proxy_manager is None:
                    self._raise_mapped_error(exc)

                is_rate_limit = self._is_rate_limit_status(exc)
                is_network_failure = self._is_network_failover_error(exc)
                is_other_http_failure = self._is_other_http_failover_status(exc)
                if (
                    not is_rate_limit
                    and not is_network_failure
                    and not is_other_http_failure
                ):
                    self._raise_mapped_error(exc)

                if is_rate_limit:
                    logger.warning(
                        "OpenRouter HTTP 429 triggering Resin route rotation "
                        "model=%s platform=%s account=%s attempt=%d",
                        self.model,
                        self.proxy_manager.platform,
                        self.proxy_manager.account,
                        attempt,
                    )
                    (
                        candidate_egress_ips,
                        rotation_count,
                        rotation_budget,
                    ) = await self._rotate_after_rate_limit(
                        exc,
                        candidate_egress_ips,
                        attempted_egress_ips,
                        rotation_count,
                        rotation_budget,
                    )
                elif is_network_failure:
                    logger.warning(
                        "OpenRouter network failure through Resin model=%s platform=%s "
                        "account=%s attempt=%d",
                        self.model,
                        self.proxy_manager.platform,
                        self.proxy_manager.account,
                        attempt,
                    )
                    await self._failover_through_resin(exc)
                else:
                    logger.warning(
                        "OpenRouter HTTP %d triggering Resin route rotation "
                        "model=%s platform=%s account=%s attempt=%d",
                        exc.status_code,
                        self.model,
                        self.proxy_manager.platform,
                        self.proxy_manager.account,
                        attempt,
                    )
                    await self._failover_through_resin(exc)
                attempt += 1
                logger.info(
                    "Retrying OpenRouter request through another Resin route "
                    "model=%s platform=%s account=%s attempt=%d",
                    self.model,
                    self.proxy_manager.platform,
                    self.proxy_manager.account,
                    attempt,
                )
        elapsed = time.perf_counter() - started
        logger.info("OpenRouter request completed elapsed=%.1fs", elapsed)
        return response
