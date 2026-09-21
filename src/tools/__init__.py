"""Tools package - MCP tool definitions organized by category."""
# Query tools (基础查询)
from .query import host_get, hostgroup_get, hostgroup_get_hosts, host_software_inventory_get, item_get, trigger_get, event_get, history_get

# Update tools (管理操作)
from .update import host_update

# Analysis tools (分析摘要)
from .analysis import trend_get, trend_summary, get_problem_summary, get_problem_fact_detail, check_host_health, quick_status, host_alert_history

# Report tools (报表)
from .report import event_daily_report, event_weekly_report, event_monthly_report

# System tools (系统信息)
from .system import apiinfo_version, get_host_by_ip

__all__ = [
    # Query tools
    "host_get",
    "hostgroup_get",
    "hostgroup_get_hosts",
    "host_software_inventory_get",
    "item_get",
    "trigger_get",
    "event_get",
    "history_get",
    # Update tools
    "host_update",
    # Analysis tools
    "trend_get",
    "trend_summary",
    "get_problem_summary",
    "get_problem_fact_detail",
    "check_host_health",
    "quick_status",
    "host_alert_history",
    # Report tools
    "event_daily_report",
    "event_weekly_report",
    "event_monthly_report",
    # System tools
    "apiinfo_version",
    "get_host_by_ip",
]
