import logging
from unittest.mock import AsyncMock
from urllib.parse import unquote, urlsplit
from uuid import UUID

import httpx
import pytest

from app.core.config import Settings
from app.research.errors import ResearchProviderConfigurationError
from app.research.proxy.resin import ResinControlError, ResinProxyManager


def resin_settings(**values):
    return Settings(
        resin_enabled=True,
        resin_proxy_url="http://127.0.0.1:2260",
        resin_proxy_token="test-token",
        resin_admin_url="http://resin.test",
        resin_admin_token="admin-token",
        resin_platform_name="OpenRouter",
        resin_platform_id=UUID("11111111-1111-1111-1111-111111111111"),
        openrouter_resin_account="openrouter-apodex",
        **values,
    )


def response(status, json=None):
    return httpx.Response(
        status,
        json=json,
        request=httpx.Request("GET", "http://resin.test/lease"),
    )


def raw_response(status, content):
    return httpx.Response(
        status,
        content=content,
        request=httpx.Request("GET", "http://resin.test/nodes"),
    )


def client_with(*, get=None, delete=None):
    return AsyncMock(
        spec=httpx.AsyncClient,
        get=(
            AsyncMock(side_effect=get)
            if isinstance(get, (Exception, list, tuple))
            else AsyncMock(return_value=get)
        ),
        delete=(
            AsyncMock(side_effect=delete)
            if isinstance(delete, (Exception, list, tuple))
            else AsyncMock(return_value=delete)
        ),
    )


def test_proxy_authentication_is_safely_url_encoded(caplog):
    caplog.set_level(logging.INFO)
    manager = ResinProxyManager(resin_settings(), client=client_with())
    parsed = urlsplit(manager.proxy_url)

    assert unquote(parsed.username) == "OpenRouter.openrouter-apodex"
    assert unquote(parsed.password) == "test-token"
    assert parsed.hostname == "127.0.0.1"
    assert parsed.port == 2260
    assert "test-token" not in caplog.text
    assert "admin-token" not in caplog.text


def test_enabled_resin_requires_control_and_proxy_configuration():
    with pytest.raises(
        ResearchProviderConfigurationError,
        match="RESIN_PROXY_TOKEN.*RESIN_ADMIN_TOKEN",
    ):
        Settings(
            resin_enabled=True,
            resin_proxy_token=None,
            resin_admin_token=None,
            resin_platform_id=None,
        )


@pytest.mark.asyncio
async def test_current_lease_parses_useful_fields():
    control = client_with(
        get=response(
            200,
            {
                "account": "openrouter-apodex",
                "node_hash": "node-123",
                "node_tag": "healthy",
                "egress_ip": "203.0.113.5",
                "expiry": "2026-10-06T12:00:00Z",
            },
        )
    )
    lease = await ResinProxyManager(resin_settings(), client=control).current_lease()

    assert lease is not None
    assert lease.account == "openrouter-apodex"
    assert lease.node_hash == "node-123"
    assert lease.egress_ip == "203.0.113.5"


@pytest.mark.asyncio
async def test_current_lease_returns_none_for_missing_lease():
    control = client_with(get=response(404))
    manager = ResinProxyManager(resin_settings(), client=control)
    assert await manager.current_lease() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [7, 0])
async def test_routable_node_count_returns_valid_count(count):
    control = client_with(
        get=response(
            200,
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "name": "OpenRouter",
                "routable_node_count": count,
            },
        )
    )
    manager = ResinProxyManager(resin_settings(), client=control)

    assert await manager.routable_node_count() == count
    control.get.assert_awaited_once_with(
        "/api/v1/platforms/11111111-1111-1111-1111-111111111111"
    )


@pytest.mark.asyncio
async def test_routable_node_count_rejects_http_failure():
    manager = ResinProxyManager(
        resin_settings(), client=client_with(get=response(500))
    )
    with pytest.raises(ResinControlError, match="HTTP 500"):
        await manager.routable_node_count()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"routable_node_count": "7"},
        {"routable_node_count": 7.0},
        {"routable_node_count": True},
        {"routable_node_count": -1},
    ],
    ids=["missing", "string", "float", "boolean", "negative"],
)
async def test_routable_node_count_rejects_malformed_payload(payload):
    manager = ResinProxyManager(
        resin_settings(), client=client_with(get=response(200, payload))
    )
    with pytest.raises(ResinControlError, match="invalid routable_node_count"):
        await manager.routable_node_count()


@pytest.mark.asyncio
async def test_routable_node_count_wraps_network_failure_without_tokens():
    request = httpx.Request("GET", "http://resin.test/platform")
    control = client_with(
        get=httpx.ConnectTimeout("admin-token test-token", request=request)
    )
    with pytest.raises(ResinControlError) as raised:
        await ResinProxyManager(resin_settings(), client=control).routable_node_count()
    assert str(raised.value) == "Resin platform inspection failed"
    assert "token" not in str(raised.value)


@pytest.mark.asyncio
async def test_routable_egress_pool_collects_unique_non_blank_ips():
    control = client_with(
        get=response(
            200,
            {
                "total": 7,
                "unique_egress_ips": 2,
                "items": [
                    {"node_hash": "a", "egress_ip": "1.1.1.1"},
                    {"node_hash": "b", "egress_ip": "1.1.1.1"},
                    {"node_hash": "c", "egress_ip": " 2.2.2.2 "},
                    {"node_hash": "d", "egress_ip": None},
                    {"node_hash": "e", "egress_ip": ""},
                    {"node_hash": "f", "egress_ip": "   "},
                    {"node_hash": "g"},
                ],
            },
        )
    )
    manager = ResinProxyManager(resin_settings(), client=control)

    pool = await manager.routable_egress_pool()

    assert pool.node_count == 7
    assert pool.egress_ips == frozenset({"1.1.1.1", "2.2.2.2"})
    assert pool.egress_ip_count == 2
    control.get.assert_awaited_once_with(
        "/api/v1/nodes",
        params={
            "platform_id": "11111111-1111-1111-1111-111111111111",
            "limit": 100_000,
            "offset": 0,
        },
    )


@pytest.mark.asyncio
async def test_routable_egress_pool_paginates_without_truncation():
    control = client_with(
        get=[
            response(
                200,
                {
                    "total": 4,
                    "unique_egress_ips": 3,
                    "items": [
                        {"egress_ip": "1.1.1.1"},
                        {"egress_ip": "2.2.2.2"},
                    ],
                },
            ),
            response(
                200,
                {
                    "total": 4,
                    "unique_egress_ips": 3,
                    "items": [
                        {"egress_ip": "2.2.2.2"},
                        {"egress_ip": "3.3.3.3"},
                    ],
                },
            ),
        ]
    )
    manager = ResinProxyManager(resin_settings(), client=control)
    manager._NODE_PAGE_LIMIT = 2

    pool = await manager.routable_egress_pool()

    assert pool.node_count == 4
    assert pool.egress_ips == frozenset({"1.1.1.1", "2.2.2.2", "3.3.3.3"})
    assert control.get.await_args_list[1].kwargs["params"]["offset"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reply",
    [
        response(500),
        raw_response(200, b"{"),
        response(200, []),
        response(200, {"total": 1, "items": {}}),
        response(200, {"total": -1, "items": []}),
        response(200, {"total": 1, "items": []}),
    ],
    ids=["http", "invalid-json", "non-object", "items", "total", "no-progress"],
)
async def test_routable_egress_pool_rejects_malformed_response(reply):
    manager = ResinProxyManager(resin_settings(), client=client_with(get=reply))
    with pytest.raises(ResinControlError):
        await manager.routable_egress_pool()


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [None, True, -1, 1.5, "1"])
async def test_routable_egress_pool_rejects_invalid_reported_unique_count(value):
    manager = ResinProxyManager(
        resin_settings(),
        client=client_with(
            get=response(
                200,
                {"total": 0, "unique_egress_ips": value, "items": []},
            )
        ),
    )
    with pytest.raises(ResinControlError, match="invalid unique_egress_ips"):
        await manager.routable_egress_pool()


@pytest.mark.asyncio
async def test_routable_egress_pool_wraps_network_failure_without_tokens():
    request = httpx.Request("GET", "http://resin.test/nodes")
    manager = ResinProxyManager(
        resin_settings(),
        client=client_with(
            get=httpx.ConnectTimeout("admin-token test-token", request=request)
        ),
    )
    with pytest.raises(ResinControlError) as raised:
        await manager.routable_egress_pool()
    assert str(raised.value) == "Resin node inspection failed"
    assert "token" not in str(raised.value)


@pytest.mark.asyncio
async def test_routable_egress_pool_allows_reported_unique_count_mismatch(caplog):
    caplog.set_level(logging.WARNING, logger="app.research.proxy.resin")
    manager = ResinProxyManager(
        resin_settings(),
        client=client_with(
            get=response(
                200,
                {
                    "total": 1,
                    "unique_egress_ips": 5,
                    "items": [{"egress_ip": "1.1.1.1"}],
                },
            )
        ),
    )

    pool = await manager.routable_egress_pool()

    assert pool.egress_ips == frozenset({"1.1.1.1"})
    assert "differs from collected nodes" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("delete_status", [204, 404])
async def test_reset_route_accepts_deleted_or_missing_lease(delete_status):
    control = client_with(get=response(404), delete=response(delete_status))
    await ResinProxyManager(resin_settings(), client=control).reset_route()
    control.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_reset_route_raises_safe_error_for_control_failure():
    control = client_with(get=response(404), delete=response(500))
    with pytest.raises(ResinControlError, match="HTTP 500") as raised:
        await ResinProxyManager(resin_settings(), client=control).reset_route()
    assert "admin-token" not in str(raised.value)
    assert "test-token" not in str(raised.value)


@pytest.mark.asyncio
async def test_reset_route_wraps_network_failure_without_tokens():
    request = httpx.Request("DELETE", "http://resin.test/lease")
    control = client_with(
        get=response(404),
        delete=httpx.ConnectTimeout("admin-token test-token", request=request),
    )
    with pytest.raises(ResinControlError) as raised:
        await ResinProxyManager(resin_settings(), client=control).reset_route()
    assert str(raised.value) == "Resin route reset failed"
    assert "token" not in str(raised.value)
