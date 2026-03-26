"""System Tools - MCP tools for system information and utilities."""
import logging
from typing import Any, Dict, List, Optional, Union

from client import get_zabbix_client
from utils.format import format_response

logger = logging.getLogger(__name__)


def apiinfo_version() -> str:
    """获取 Zabbix API 版本信息。

    用于确认 Zabbix 服务器版本和 API 兼容性，
    在调试连接问题或确认 API 功能支持时特别有用。

    Returns:
        JSON 格式的 API 版本信息，包含版本号字符串

    使用场景：
        - 场景1：确认 Zabbix 服务器版本
          apiinfo_version()
        - 场景2：调试连接问题时验证 API 可访问性
          apiinfo_version()
    """
    client = get_zabbix_client()
    result = client.apiinfo.version()
    return format_response(result)


def get_host_by_ip(ip: str) -> str:
    """通过IP地址精确获取主机的hostid和名称。
    这是最节省Token的定位方式，建议在已知IP时优先使用。

    Args:
        ip: 主机的IP地址 (例如 "192.168.1.1")
    """
    client = get_zabbix_client()

    # 调用 hostinterface.get
    params = {
        "output": ["hostid"],
        "selectHosts": ["hostid", "name", "status"],
        "filter": {
            "ip": ip
        }
    }

    result = client.hostinterface.get(**params)

    if not result:
        return f"未找到 IP 为 {ip} 的主机接口配置。"

    # 提取主机信息
    hosts = result[0].get("hosts", [])
    if not hosts:
        return f"找到接口但未关联主机，IP: {ip}"

    # 只返回最核心的信息，极度节省Token
    return format_response(hosts)
