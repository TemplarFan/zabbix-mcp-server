"""配置模块 - 存放可调参数与来自环境变量的运行配置"""

import ipaddress
import logging
import os

# ===== src/tools/analysis.py - host_alert_history =====

JITTER_THRESHOLD_SECONDS = 180  # 抖动阈值（秒）
CHRONIC_THRESHOLD_SECONDS = 3600  # 持续阈值（秒）
BEFORE_WINDOW_HOURS = 2  # 前置告警查询窗口（小时）
DEFAULT_QUERY_DAYS = 7  # 默认查询天数

# ===== 生产口径测试网段过滤 =====
# 报表工具的 production_only 模式排除命中以下网段的主机；
# 网段通过环境变量配置（逗号分隔 CIDR，如 192.168.100.0/24,192.168.101.0/24）。
TEST_NETWORKS_ENV_VAR = "ZABBIX_TEST_NETWORKS"

_cached_networks_env: str | None = None
_cached_test_networks: tuple[ipaddress.IPv4Network, ...] = ()


def get_test_host_networks() -> tuple[ipaddress.IPv4Network, ...]:
    """读取测试网段配置并解析为 ip_network 元组。

    按环境变量当前值缓存解析结果，配置变化时自动重新解析；
    无法解析的条目跳过并记录告警，未配置时返回空元组。
    """
    global _cached_networks_env, _cached_test_networks
    raw = os.environ.get(TEST_NETWORKS_ENV_VAR, "")
    if raw != _cached_networks_env:
        networks = []
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                networks.append(ipaddress.ip_network(part, strict=False))
            except ValueError:
                logging.warning("Ignoring invalid entry in %s: %r", TEST_NETWORKS_ENV_VAR, part)
        _cached_networks_env = raw
        _cached_test_networks = tuple(networks)
    return _cached_test_networks


# ===== 工具级开关与来源白名单（安全加固） =====
# 拒绝清单中的工具在注册期直接移除（模型不可见）；留空 = 全部启用。
DENIED_TOOLS_ENV = "ZABBIX_DENY_TOOLS"

# HTTP 传输的来源 IP/CIDR 白名单；留空 = 放行所有（opt-in）。
ALLOWED_IPS_ENV = "ZABBIX_ALLOWED_IPS"

_cached_denied_env: str | None = None
_cached_denied_tools: tuple[str, ...] = ()

_cached_allowed_env: str | None = None
_cached_allowed_networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = ()


def get_denied_tools() -> tuple[str, ...]:
    """读取拒绝工具名单（逗号分隔工具名）；留空返回空元组，按当前值缓存。"""
    global _cached_denied_env, _cached_denied_tools
    raw = os.environ.get(DENIED_TOOLS_ENV, "")
    if raw != _cached_denied_env:
        names = tuple(part.strip() for part in raw.split(",") if part.strip())
        _cached_denied_env = raw
        _cached_denied_tools = names
    return _cached_denied_tools


def get_allowed_ip_networks() -> tuple:
    """读取来源白名单并解析为 ip_network 元组（裸 IP 视为 /32）。

    留空返回空元组（调用方语义：不限制）；无效条目跳过并告警。
    """
    global _cached_allowed_env, _cached_allowed_networks
    raw = os.environ.get(ALLOWED_IPS_ENV, "")
    if raw != _cached_allowed_env:
        networks = []
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                networks.append(ipaddress.ip_network(part, strict=False))
            except ValueError:
                logging.warning("Ignoring invalid entry in %s: %r", ALLOWED_IPS_ENV, part)
        _cached_allowed_env = raw
        _cached_allowed_networks = tuple(networks)
    return _cached_allowed_networks
