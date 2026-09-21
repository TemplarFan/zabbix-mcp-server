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
