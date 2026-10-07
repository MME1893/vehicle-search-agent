import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import httpx2
import pytest
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    RateLimitError,
)

from app.core.config import Settings
from app.research.errors import (
    ProviderAuthenticationError,
    ProviderQuotaError,
    ProviderRateLimitError,
)
from app.research.providers.openrouter.client import (
    OpenRouterClient,
    OpenRouterConfigurationError,
    OpenRouterProviderError,
    OpenRouterTimeoutError,
)
from app.research.proxy.resin import ResinControlError, ResinEgressPool, ResinLease


def configured_settings(**values):
    values.setdefault("resin_enabled", False)
    return Settings(
        openrouter_api_key="test-key",
        openrouter_model="test/model",
        openrouter_base_url="https://openrouter.test/v1",
        openrouter_timeout_seconds=12,
        **values,
    )


def resin_settings(**values):
    return configured_settings(
        resin_enabled=True,
        resin_proxy_token="proxy-secret",
        resin_admin_token="admin-secret",
        resin_platform_id=UUID("11111111-1111-1111-1111-111111111111"),
        **values,
    )


def sdk_with_create(create):
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def proxy_manager(
    reset_side_effect=None,
    routable_side_effect=None,
    *,
    candidate_egress_ips=("A",),
    pool_side_effect=None,
    lease_side_effect=None,
):
    reset = AsyncMock(side_effect=reset_side_effect)
    routable = AsyncMock(
        return_value=1 if routable_side_effect is None else None,
        side_effect=routable_side_effect,
    )
    pool = AsyncMock(
        return_value=(
            ResinEgressPool(
                node_count=len(candidate_egress_ips),
                egress_ips=frozenset(candidate_egress_ips),
            )
            if pool_side_effect is None
            else None
        ),
        side_effect=pool_side_effect,
    )
    current_lease = AsyncMock(
        return_value=(
            ResinLease(account="openrouter-default", node_hash="node-A", egress_ip="A")
            if lease_side_effect is None
            else None
        ),
        side_effect=lease_side_effect,
    )
    return SimpleNamespace(
        platform="OpenRouter",
        account="openrouter-default",
        proxy_url="http://proxy.example",
        reset_route=reset,
        routable_node_count=routable,
        routable_egress_pool=pool,
        current_lease=current_lease,
        aclose=AsyncMock(),
    )


def connection_error():
    return APIConnectionError(
        request=httpx2.Request("POST", "https://openrouter.test")
    )


def timeout_error(cause=None):
    error = APITimeoutError(
        request=httpx2.Request("POST", "https://openrouter.test")
    )
    if cause is not None:
        error.__cause__ = cause
    return error


def status_error(status):
    response = httpx2.Response(
        status,
        request=httpx2.Request("POST", "https://openrouter.test"),
    )
    if status == 401:
        return AuthenticationError("bad auth", response=response, body=None)
    if status == 429:
        return RateLimitError("slow", response=response, body=None)
    return APIStatusError("failed", response=response, body=None)


def test_missing_api_key_or_model_is_configuration_error():
    with pytest.raises(OpenRouterConfigurationError, match="API_KEY"):
        OpenRouterClient(Settings(openrouter_api_key=None, openrouter_model="m"))
    with pytest.raises(OpenRouterConfigurationError, match="MODEL"):
        OpenRouterClient(Settings(openrouter_api_key="k", openrouter_model=None))


def test_sdk_disables_retries_without_resin_transport(monkeypatch):
    factory = MagicMock()
    monkeypatch.setattr("app.research.providers.openrouter.client.AsyncOpenAI", factory)
    OpenRouterClient(configured_settings())
    kwargs = factory.call_args.kwargs
    assert kwargs["api_key"] == "test-key"
    assert kwargs["base_url"] == "https://openrouter.test/v1"
    assert kwargs["timeout"] == 12
    assert kwargs["max_retries"] == 0
    assert "http_client" not in kwargs


def test_sdk_receives_resin_httpx2_transport(monkeypatch):
    sdk_factory = MagicMock()
    transport = object()
    transport_factory = MagicMock(return_value=transport)
    manager = proxy_manager()
    manager.proxy_url = "http://OpenRouter.openrouter-default:secret@127.0.0.1:2260"
    monkeypatch.setattr("app.research.providers.openrouter.client.AsyncOpenAI", sdk_factory)
    monkeypatch.setattr(
        "app.research.providers.openrouter.client.DefaultAsyncHttpx2Client",
        transport_factory,
    )

    OpenRouterClient(resin_settings(), proxy_manager=manager)

    transport_factory.assert_called_once_with(proxy=manager.proxy_url)
    assert sdk_factory.call_args.kwargs["http_client"] is transport
    assert sdk_factory.call_args.kwargs["max_retries"] == 0


@pytest.mark.asyncio
async def test_completion_passes_model_messages_and_tools(caplog):
    caplog.set_level(logging.INFO, logger="app.research.providers.openrouter.client")
    create = AsyncMock(return_value=object())
    client = OpenRouterClient(configured_settings(), client=sdk_with_create(create))
    messages = [{"role": "user", "content": "research"}]
    tools = [{"type": "openrouter:web_search"}]
    await client.create_completion(messages=messages, tools=tools)
    create.assert_awaited_once_with(model="test/model", messages=messages, tools=tools)
    assert "OpenRouter request started model=test/model web_search=true" in caplog.text
    assert "OpenRouter request completed elapsed=" in caplog.text


@pytest.mark.asyncio
async def test_multiple_network_failures_retry_until_success():
    result = object()
    create = AsyncMock(
        side_effect=[
            connection_error(),
            connection_error(),
            connection_error(),
            result,
        ]
    )
    manager = proxy_manager(routable_side_effect=[5, 4, 3])
    client = OpenRouterClient(
        resin_settings(), client=sdk_with_create(create), proxy_manager=manager
    )

    assert await client.create_completion(messages=[]) is result
    assert create.await_count == 4
    assert manager.reset_route.await_count == 3
    assert manager.routable_node_count.await_count == 3


@pytest.mark.asyncio
async def test_network_failover_stops_when_routable_pool_is_exhausted():
    create = AsyncMock(
        side_effect=[connection_error(), connection_error(), connection_error()]
    )
    manager = proxy_manager(routable_side_effect=[2, 1, 0])
    client = OpenRouterClient(
        resin_settings(), client=sdk_with_create(create), proxy_manager=manager
    )

    with pytest.raises(OpenRouterProviderError, match="connection failed"):
        await client.create_completion(messages=[])
    assert create.await_count == 3
    assert manager.reset_route.await_count == 3
    assert manager.routable_node_count.await_count == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cause",
    [
        httpx2.ReadTimeout(
            "slow response", request=httpx2.Request("POST", "https://example.test")
        ),
        None,
    ],
    ids=["read-timeout", "unknown-cause"],
)
async def test_non_connect_timeout_does_not_rotate(cause):
    create = AsyncMock(side_effect=timeout_error(cause))
    manager = proxy_manager()
    client = OpenRouterClient(
        resin_settings(), client=sdk_with_create(create), proxy_manager=manager
    )

    with pytest.raises(OpenRouterTimeoutError, match="timed out after 12 seconds"):
        await client.create_completion(messages=[])
    manager.reset_route.assert_not_awaited()
    manager.routable_node_count.assert_not_awaited()
    assert create.await_count == 1


@pytest.mark.asyncio
async def test_multiple_connect_timeouts_retry_until_success():
    def connect_timeout():
        cause = httpx2.ConnectTimeout(
            "connect failed", request=httpx2.Request("POST", "https://example.test")
        )
        return timeout_error(cause)

    result = object()
    create = AsyncMock(
        side_effect=[connect_timeout(), connect_timeout(), connect_timeout(), result]
    )
    manager = proxy_manager(routable_side_effect=[6, 5, 4])
    client = OpenRouterClient(
        resin_settings(), client=sdk_with_create(create), proxy_manager=manager
    )

    assert await client.create_completion(messages=[]) is result
    assert create.await_count == 4
    assert manager.reset_route.await_count == 3
    assert manager.routable_node_count.await_count == 3


@pytest.mark.asyncio
async def test_http_403_failover_stops_only_when_pool_is_exhausted(caplog):
    caplog.set_level(logging.INFO, logger="app.research.providers.openrouter.client")
    create = AsyncMock(
        side_effect=[status_error(403), status_error(403), status_error(403)]
    )
    manager = proxy_manager(routable_side_effect=[2, 1, 0])
    client = OpenRouterClient(
        resin_settings(), client=sdk_with_create(create), proxy_manager=manager
    )

    with pytest.raises(OpenRouterProviderError):
        await client.create_completion(messages=[])
    assert create.await_count == 3
    assert manager.reset_route.await_count == 3
    assert manager.routable_node_count.await_count == 3
    assert "OpenRouter HTTP 403 triggering Resin route rotation" in caplog.text
    assert "OpenRouter network failure through Resin" not in caplog.text
    manager.routable_egress_pool.assert_not_awaited()


@pytest.mark.asyncio
async def test_http_and_network_failures_share_pool_aware_retry_loop():
    result = object()
    create = AsyncMock(
        side_effect=[
            status_error(429),
            status_error(429),
            connection_error(),
            result,
        ]
    )
    manager = proxy_manager(
        routable_side_effect=[2],
        candidate_egress_ips=("A", "B", "C"),
        lease_side_effect=[
            ResinLease(account="openrouter-default", egress_ip="A"),
            ResinLease(account="openrouter-default", egress_ip="B"),
        ],
    )
    client = OpenRouterClient(
        resin_settings(), client=sdk_with_create(create), proxy_manager=manager
    )

    assert await client.create_completion(messages=[]) is result
    assert create.await_count == 4
    assert manager.reset_route.await_count == 3
    assert manager.routable_node_count.await_count == 1
    manager.routable_egress_pool.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_429_snapshots_candidates_once_and_stops_on_distinct_exhaustion():
    create = AsyncMock(
        side_effect=[status_error(429), status_error(429), status_error(429)]
    )
    manager = proxy_manager(
        candidate_egress_ips=("A", "B", "C"),
        lease_side_effect=[
            ResinLease(account="openrouter-default", egress_ip=ip)
            for ip in ("A", "B", "C")
        ],
    )
    client = OpenRouterClient(
        resin_settings(), client=sdk_with_create(create), proxy_manager=manager
    )

    with pytest.raises(ProviderRateLimitError, match="rate limit exceeded"):
        await client.create_completion(messages=[])

    assert create.await_count == 3
    assert manager.reset_route.await_count == 2
    manager.routable_egress_pool.assert_awaited_once_with()
    assert manager.current_lease.await_count == 3
    manager.routable_node_count.assert_not_awaited()


@pytest.mark.asyncio
async def test_429_duplicate_egress_selections_count_only_once(caplog):
    caplog.set_level(logging.INFO, logger="app.research.providers.openrouter.client")
    sequence = ("A", "A", "B", "A", "C")
    create = AsyncMock(side_effect=[status_error(429) for _ in sequence])
    manager = proxy_manager(
        candidate_egress_ips=("A", "B", "C"),
        lease_side_effect=[
            ResinLease(account="openrouter-default", egress_ip=ip)
            for ip in sequence
        ],
    )
    client = OpenRouterClient(
        resin_settings(), client=sdk_with_create(create), proxy_manager=manager
    )

    with pytest.raises(ProviderRateLimitError):
        await client.create_completion(messages=[])

    assert create.await_count == 5
    assert manager.reset_route.await_count == 4
    assert "attempted_egress_count=3 candidate_egress_count=3" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("candidate_count", [1, 3, 9])
async def test_429_rotation_budget_is_twice_candidate_count(candidate_count):
    expected_budget = candidate_count * 2
    create = AsyncMock(
        side_effect=[status_error(429) for _ in range(expected_budget + 1)]
    )
    manager = proxy_manager(
        candidate_egress_ips=tuple(f"candidate-{index}" for index in range(candidate_count)),
        lease_side_effect=[
            ResinLease(account="openrouter-default", egress_ip="outside-snapshot")
            for _ in range(expected_budget + 1)
        ],
    )
    client = OpenRouterClient(
        resin_settings(), client=sdk_with_create(create), proxy_manager=manager
    )

    with pytest.raises(ProviderRateLimitError):
        await client.create_completion(messages=[])

    assert create.await_count == expected_budget + 1
    assert manager.reset_route.await_count == expected_budget
    manager.routable_egress_pool.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_429_empty_candidate_pool_does_not_rotate():
    create = AsyncMock(side_effect=status_error(429))
    manager = proxy_manager(candidate_egress_ips=())
    client = OpenRouterClient(
        resin_settings(), client=sdk_with_create(create), proxy_manager=manager
    )

    with pytest.raises(ProviderRateLimitError):
        await client.create_completion(messages=[])

    assert create.await_count == 1
    manager.current_lease.assert_not_awaited()
    manager.reset_route.assert_not_awaited()


@pytest.mark.asyncio
async def test_429_missing_lease_is_bounded_by_rotation_budget():
    create = AsyncMock(side_effect=[status_error(429) for _ in range(5)])
    manager = proxy_manager(
        candidate_egress_ips=("A", "B"),
        lease_side_effect=[None, None, None, None, None],
    )
    client = OpenRouterClient(
        resin_settings(), client=sdk_with_create(create), proxy_manager=manager
    )

    with pytest.raises(ProviderRateLimitError):
        await client.create_completion(messages=[])

    assert create.await_count == 5
    assert manager.reset_route.await_count == 4


@pytest.mark.asyncio
async def test_429_egress_outside_snapshot_does_not_expand_candidates(caplog):
    caplog.set_level(logging.INFO, logger="app.research.providers.openrouter.client")
    result = object()
    create = AsyncMock(side_effect=[status_error(429), result])
    manager = proxy_manager(
        candidate_egress_ips=("A", "B", "C"),
        lease_side_effect=[ResinLease(account="openrouter-default", egress_ip="D")],
    )
    client = OpenRouterClient(
        resin_settings(), client=sdk_with_create(create), proxy_manager=manager
    )

    assert await client.create_completion(messages=[]) is result
    assert manager.reset_route.await_count == 1
    assert "egress outside initial snapshot" in caplog.text
    assert "attempted_egress_count=1 candidate_egress_count=3" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_point", ["snapshot", "lease", "reset"])
async def test_429_resin_control_failure_preserves_rate_limit(failure_point):
    error = ResinControlError("control unavailable")
    kwargs = {"candidate_egress_ips": ("A", "B")}
    if failure_point == "snapshot":
        kwargs["pool_side_effect"] = error
    elif failure_point == "lease":
        kwargs["lease_side_effect"] = error
    else:
        kwargs["reset_side_effect"] = error
        kwargs["lease_side_effect"] = [
            ResinLease(account="openrouter-default", egress_ip="A")
        ]
    manager = proxy_manager(**kwargs)
    create = AsyncMock(side_effect=status_error(429))
    client = OpenRouterClient(
        resin_settings(), client=sdk_with_create(create), proxy_manager=manager
    )

    with pytest.raises(ProviderRateLimitError) as raised:
        await client.create_completion(messages=[])

    assert isinstance(raised.value.__cause__, RateLimitError)
    assert str(raised.value) == "OpenRouter rate limit exceeded"
    assert create.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected"),
    [(401, ProviderAuthenticationError), (402, ProviderQuotaError)],
)
async def test_auth_and_quota_never_rotate(status, expected):
    create = AsyncMock(side_effect=status_error(status))
    manager = proxy_manager()
    client = OpenRouterClient(
        resin_settings(), client=sdk_with_create(create), proxy_manager=manager
    )

    with pytest.raises(expected):
        await client.create_completion(messages=[])
    manager.reset_route.assert_not_awaited()
    manager.routable_node_count.assert_not_awaited()
    assert create.await_count == 1


@pytest.mark.asyncio
async def test_other_http_status_does_not_rotate():
    create = AsyncMock(side_effect=status_error(500))
    manager = proxy_manager()
    client = OpenRouterClient(
        resin_settings(), client=sdk_with_create(create), proxy_manager=manager
    )

    with pytest.raises(OpenRouterProviderError, match="HTTP 500"):
        await client.create_completion(messages=[])
    manager.reset_route.assert_not_awaited()
    manager.routable_node_count.assert_not_awaited()
    assert create.await_count == 1


@pytest.mark.asyncio
async def test_failed_route_reset_preserves_original_network_error():
    create = AsyncMock(side_effect=connection_error())
    manager = proxy_manager(ResinControlError("control unavailable"))
    client = OpenRouterClient(
        resin_settings(), client=sdk_with_create(create), proxy_manager=manager
    )

    with pytest.raises(OpenRouterProviderError, match="connection failed") as raised:
        await client.create_completion(messages=[])
    assert isinstance(raised.value.__cause__, APIConnectionError)
    assert create.await_count == 1
    manager.reset_route.assert_awaited_once_with()
    manager.routable_node_count.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_pool_inspection_preserves_original_network_error():
    create = AsyncMock(side_effect=connection_error())
    manager = proxy_manager(
        routable_side_effect=ResinControlError("control unavailable")
    )
    client = OpenRouterClient(
        resin_settings(), client=sdk_with_create(create), proxy_manager=manager
    )

    with pytest.raises(OpenRouterProviderError, match="connection failed") as raised:
        await client.create_completion(messages=[])
    assert isinstance(raised.value.__cause__, APIConnectionError)
    assert create.await_count == 1
    manager.reset_route.assert_awaited_once_with()
    manager.routable_node_count.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_owned_client_is_closed_and_rebuilt_for_next_resin_route(monkeypatch):
    result = object()
    first = sdk_with_create(AsyncMock(side_effect=status_error(403)))
    first.close = AsyncMock()
    second = sdk_with_create(AsyncMock(return_value=result))
    second.close = AsyncMock()
    sdk_factory = MagicMock(side_effect=[first, second])
    transport_factory = MagicMock(side_effect=[object(), object()])
    manager = proxy_manager(routable_side_effect=[2])
    monkeypatch.setattr("app.research.providers.openrouter.client.AsyncOpenAI", sdk_factory)
    monkeypatch.setattr(
        "app.research.providers.openrouter.client.DefaultAsyncHttpx2Client",
        transport_factory,
    )
    client = OpenRouterClient(resin_settings(), proxy_manager=manager)

    assert await client.create_completion(messages=[]) is result
    first.close.assert_awaited_once_with()
    assert sdk_factory.call_count == 2
    assert transport_factory.call_count == 2


@pytest.mark.asyncio
async def test_429_route_reset_closes_and_rebuilds_owned_transport(monkeypatch):
    result = object()
    first = sdk_with_create(AsyncMock(side_effect=status_error(429)))
    first.close = AsyncMock()
    second = sdk_with_create(AsyncMock(return_value=result))
    second.close = AsyncMock()
    sdk_factory = MagicMock(side_effect=[first, second])
    transport_factory = MagicMock(side_effect=[object(), object()])
    manager = proxy_manager(
        candidate_egress_ips=("A", "B"),
        lease_side_effect=[ResinLease(account="openrouter-default", egress_ip="A")],
    )
    monkeypatch.setattr("app.research.providers.openrouter.client.AsyncOpenAI", sdk_factory)
    monkeypatch.setattr(
        "app.research.providers.openrouter.client.DefaultAsyncHttpx2Client",
        transport_factory,
    )
    client = OpenRouterClient(resin_settings(), proxy_manager=manager)

    assert await client.create_completion(messages=[]) is result
    first.close.assert_awaited_once_with()
    manager.reset_route.assert_awaited_once_with()
    assert sdk_factory.call_count == 2
    assert transport_factory.call_count == 2


@pytest.mark.asyncio
async def test_direct_mode_preserves_existing_typed_error_mapping():
    for status, expected in (
        (401, ProviderAuthenticationError),
        (402, ProviderQuotaError),
        (403, OpenRouterProviderError),
        (429, ProviderRateLimitError),
    ):
        create = AsyncMock(side_effect=status_error(status))
        with pytest.raises(expected):
            await OpenRouterClient(
                configured_settings(), client=sdk_with_create(create)
            ).create_completion(messages=[])
        assert create.await_count == 1


@pytest.mark.asyncio
async def test_direct_mode_connection_and_connect_timeout_do_not_retry():
    connect_cause = httpx2.ConnectTimeout(
        "connect failed", request=httpx2.Request("POST", "https://example.test")
    )
    for error in (connection_error(), timeout_error(connect_cause)):
        create = AsyncMock(side_effect=error)
        client = OpenRouterClient(
            configured_settings(), client=sdk_with_create(create)
        )
        with pytest.raises(OpenRouterProviderError, match="connection failed"):
            await client.create_completion(messages=[])
        assert create.await_count == 1
