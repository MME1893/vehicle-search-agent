import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)


class ResinControlError(RuntimeError):
    """A safe failure raised by Resin's lease control plane."""


@dataclass(frozen=True)
class ResinLease:
    account: str
    node_hash: str | None = None
    node_tag: str | None = None
    egress_ip: str | None = None
    expiry: str | None = None


@dataclass(frozen=True)
class ResinEgressPool:
    node_count: int
    egress_ips: frozenset[str]

    @property
    def egress_ip_count(self) -> int:
        return len(self.egress_ips)


class ResinProxyManager:
    _NODE_PAGE_LIMIT = 100_000

    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not settings.resin_proxy_token:
            raise ValueError("Resin proxy token is required")
        if not settings.resin_admin_token:
            raise ValueError("Resin admin token is required")
        if settings.resin_platform_id is None:
            raise ValueError("Resin platform ID is required")

        self.platform = settings.resin_platform_name
        self.platform_id = settings.resin_platform_id
        self.account = settings.openrouter_resin_account
        self._proxy_url = self._authenticated_proxy_url(
            settings.resin_proxy_url,
            f"{self.platform}.{self.account}",
            settings.resin_proxy_token,
        )
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=settings.resin_admin_url,
            headers={"Authorization": f"Bearer {settings.resin_admin_token}"},
            timeout=settings.resin_control_timeout_seconds,
        )

    @staticmethod
    def _authenticated_proxy_url(proxy_url: str, username: str, password: str) -> str:
        parsed = urlsplit(proxy_url)
        if not parsed.scheme or not parsed.hostname:
            raise ValueError("RESIN_PROXY_URL must be an absolute URL")
        host = parsed.hostname
        if ":" in host:
            host = f"[{host}]"
        if parsed.port is not None:
            host = f"{host}:{parsed.port}"
        credentials = f"{quote(username, safe='')}:{quote(password, safe='')}"
        return urlunsplit(
            (parsed.scheme, f"{credentials}@{host}", parsed.path, parsed.query, parsed.fragment)
        )

    @property
    def proxy_url(self) -> str:
        return self._proxy_url

    @property
    def _lease_path(self) -> str:
        account = quote(self.account, safe="")
        return f"/api/v1/platforms/{self.platform_id}/leases/{account}"

    @property
    def _platform_path(self) -> str:
        return f"/api/v1/platforms/{self.platform_id}"

    async def routable_node_count(self) -> int:
        try:
            response = await self._client.get(self._platform_path)
        except httpx.HTTPError as exc:
            raise ResinControlError("Resin platform inspection failed") from exc
        if response.status_code != 200:
            raise ResinControlError(
                f"Resin platform inspection returned HTTP {response.status_code}"
            )
        try:
            data = response.json()
        except (TypeError, ValueError) as exc:
            raise ResinControlError(
                "Resin platform inspection returned invalid JSON"
            ) from exc
        if not isinstance(data, dict):
            raise ResinControlError("Resin platform inspection returned invalid data")
        count = data.get("routable_node_count")
        if type(count) is not int or count < 0:
            raise ResinControlError(
                "Resin platform inspection returned invalid routable_node_count"
            )
        return count

    async def routable_egress_pool(self) -> ResinEgressPool:
        offset = 0
        node_count: int | None = None
        reported_unique_counts: set[int] = set()
        egress_ips: set[str] = set()

        while True:
            try:
                response = await self._client.get(
                    "/api/v1/nodes",
                    params={
                        "platform_id": str(self.platform_id),
                        "limit": self._NODE_PAGE_LIMIT,
                        "offset": offset,
                    },
                )
            except httpx.HTTPError as exc:
                raise ResinControlError("Resin node inspection failed") from exc
            if response.status_code != 200:
                raise ResinControlError(
                    f"Resin node inspection returned HTTP {response.status_code}"
                )
            try:
                data = response.json()
            except (TypeError, ValueError) as exc:
                raise ResinControlError(
                    "Resin node inspection returned invalid JSON"
                ) from exc
            if not isinstance(data, dict):
                raise ResinControlError("Resin node inspection returned invalid data")

            items = data.get("items")
            total = data.get("total")
            if not isinstance(items, list):
                raise ResinControlError(
                    "Resin node inspection returned invalid items"
                )
            if type(total) is not int or total < 0:
                raise ResinControlError(
                    "Resin node inspection returned invalid total"
                )
            if offset == 0 and len(items) > total:
                raise ResinControlError(
                    "Resin node inspection returned invalid pagination"
                )
            if "unique_egress_ips" in data:
                reported_unique = data["unique_egress_ips"]
                if type(reported_unique) is not int or reported_unique < 0:
                    raise ResinControlError(
                        "Resin node inspection returned invalid unique_egress_ips"
                    )
                reported_unique_counts.add(reported_unique)

            if node_count is None:
                node_count = total
            for item in items:
                if not isinstance(item, dict):
                    raise ResinControlError(
                        "Resin node inspection returned invalid node item"
                    )
                egress_ip = item.get("egress_ip")
                if egress_ip is None:
                    continue
                if not isinstance(egress_ip, str):
                    raise ResinControlError(
                        "Resin node inspection returned invalid egress_ip"
                    )
                normalized = egress_ip.strip()
                if normalized:
                    egress_ips.add(normalized)

            traversed = offset + len(items)
            if traversed >= total:
                break
            if not items:
                raise ResinControlError(
                    "Resin node inspection returned invalid pagination"
                )
            offset = traversed

        assert node_count is not None
        actual_unique_count = len(egress_ips)
        if any(count != actual_unique_count for count in reported_unique_counts):
            logger.warning(
                "Resin reported unique egress count differs from collected nodes "
                "platform=%s account=%s reported_unique_egress_counts=%s "
                "collected_egress_ip_count=%d",
                self.platform,
                self.account,
                sorted(reported_unique_counts),
                actual_unique_count,
            )
        return ResinEgressPool(
            node_count=node_count,
            egress_ips=frozenset(egress_ips),
        )

    async def current_lease(self) -> ResinLease | None:
        try:
            response = await self._client.get(self._lease_path)
        except httpx.HTTPError as exc:
            raise ResinControlError("Resin lease inspection failed") from exc
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise ResinControlError(
                f"Resin lease inspection returned HTTP {response.status_code}"
            )
        try:
            data: dict[str, Any] = response.json()
        except (TypeError, ValueError) as exc:
            raise ResinControlError("Resin lease inspection returned invalid JSON") from exc
        return ResinLease(
            account=str(data.get("account") or self.account),
            node_hash=data.get("node_hash"),
            node_tag=data.get("node_tag"),
            egress_ip=data.get("egress_ip"),
            expiry=data.get("expiry") or data.get("expires_at"),
        )

    async def reset_route(self) -> None:
        lease = None
        try:
            lease = await self.current_lease()
        except ResinControlError:
            logger.warning(
                "Resin lease inspection failed before route reset platform=%s account=%s",
                self.platform,
                self.account,
            )
        logger.info(
            "Resin route reset requested platform=%s account=%s node_hash=%s egress_ip=%s",
            self.platform,
            self.account,
            lease.node_hash if lease else None,
            lease.egress_ip if lease else None,
        )
        try:
            response = await self._client.delete(self._lease_path)
        except httpx.HTTPError as exc:
            raise ResinControlError("Resin route reset failed") from exc
        if response.status_code not in (204, 404):
            raise ResinControlError(
                f"Resin route reset returned HTTP {response.status_code}"
            )
        logger.info(
            "Resin route reset completed platform=%s account=%s",
            self.platform,
            self.account,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
