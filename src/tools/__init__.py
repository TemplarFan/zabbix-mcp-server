"""Tools package - MCP tool definitions organized by category."""
# Host tools (主机查询)
from .host import host_get, host_software_inventory_get
# Group tools (主机组查询)
from .group import hostgroup_get, hostgroup_get_hosts
# Item tools (监控项查询)
from .item import item_get
# Trigger tools (触发器与模板查询)
from .trigger import trigger_get, template_get
# Event tools (事件查询)
from .event import event_get
# Update tools (管理操作)
from .update import host_update
# History tools (历史查询)
from .history import history_get

# Analysis tools (分析摘要)
from .trend import trend_get, trend_summary
from .problem import get_problem_summary, get_problem_fact_detail
from .health import check_host_health, quick_status
from .history import host_alert_history
# Report tools (报表)
from .report import event_daily_report, event_weekly_report, event_monthly_report
# System tools (系统信息)
from .system import apiinfo_version, get_host_by_ip

__all__ = [
    # Host tools
    "host_get",
    "host_software_inventory_get",
    # Group tools
    "hostgroup_get",
    "hostgroup_get_hosts",
    # Item tools
    "item_get",
    # Trigger tools
    "trigger_get",
    "template_get",
    # Event tools
    "event_get",
    # History tools
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
