"""报表查询模块所需的最小 Zabbix 客户端协议。"""

from typing import Any, Protocol


class ZabbixCallClient(Protocol):
    """仅约束报表需要的只读 JSON-RPC 调用接口。"""

    def call(
        self,
        method: str,
        params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """调用 Zabbix API 并返回列表结果，失败时应抛出异常。"""
        ...
