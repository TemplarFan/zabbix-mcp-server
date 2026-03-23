"""Tools package - MCP tool definitions organized by category."""
# Query tools (基础查询)
from tools.query import host_get, item_get, trigger_get, event_get, history_get

# Analysis tools (分析摘要)
from tools.analysis import trend_get, trend_summary, get_problem_summary, check_host_health, quick_status

# System tools (系统信息)
from tools.system import apiinfo_version, get_host_by_ip

__all__ = [
    # Query tools
    "host_get",
    "item_get",
    "trigger_get",
    "event_get",
    "history_get",
    # Analysis tools
    "trend_get",
    "trend_summary",
    "get_problem_summary",
    "check_host_health",
    "quick_status",
    # System tools
    "apiinfo_version",
    "get_host_by_ip",
]
