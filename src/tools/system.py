"""System Tools - MCP tools for system information and utilities."""
import logging
from typing import Annotated

from pydantic import Field

from client import get_zabbix_client
from utils.format import format_response

logger = logging.getLogger(__name__)


def _apiinfo_version_impl(client):
    """获取Zabbix API版本信息"""
    result = client.apiinfo.version()
    return format_response(result)


def apiinfo_version() -> str:
    """获取Zabbix API版本信息"""
    return _apiinfo_version_impl(get_zabbix_client())


def _get_host_by_ip_impl(client, ip):
    """通过IP精确查询主机。已知IP时优先用此工具，比host_get更精准省Token"""
    params = {
        "output": ["hostid"],
        "selectHosts": ["hostid", "name", "status"],
        "filter": {"ip": ip}
    }

    result = client.hostinterface.get(**params)

    if not result:
        return f"未找到 IP 为 {ip} 的主机接口配置"

    hosts = result[0].get("hosts", [])
    if not hosts:
        return f"找到接口但未关联主机，IP: {ip}"

    return format_response(hosts)

def get_host_by_ip(
    ip: Annotated[str, Field(description="主机IP地址")]
) -> str:
    """通过IP精确查询主机。已知IP时优先用此工具，比host_get更精准省Token"""
    return _get_host_by_ip_impl(get_zabbix_client(), ip)
