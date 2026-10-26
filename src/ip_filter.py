"""HTTP 传输的来源 IP 白名单中间件。

ZABBIX_ALLOWED_IPS 未配置（空）时放行所有请求；配置后仅放行
命中名单（IP 或 CIDR）的来源，其余返回 403。仅在 streamable-http
传输挂载；stdio 无网络面，不受影响。白名单解析见 config.get_allowed_ip_networks。
"""

from __future__ import annotations

import ipaddress
from typing import Any, Awaitable, Callable

from config import get_allowed_ip_networks
from starlette.responses import PlainTextResponse


class IPFilterMiddleware:
    """纯 ASGI 中间件：按 scope["client"] 的来源地址校验白名单。"""

    def __init__(self, app: Callable[..., Awaitable[None]]):
        self.app = app

    async def __call__(self, scope: dict, receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        networks = get_allowed_ip_networks()
        if networks:
            client: Any = scope.get("client")
            host = client[0] if client else ""
            allowed = False
            if host:
                try:
                    address = ipaddress.ip_address(host)
                except ValueError:
                    address = None
                if address is not None:
                    allowed = any(address in network for network in networks)
            if not allowed:
                response = PlainTextResponse(
                    "403 Forbidden: 来源 IP 不在 ZABBIX_ALLOWED_IPS 白名单内",
                    status_code=403,
                )
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)
