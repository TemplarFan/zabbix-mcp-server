"""MCP 内部报表查询与 Markdown 生成模块。"""

from .daily import generate_daily_report
from .monthly import generate_monthly_report
from .weekly import generate_weekly_report

__all__ = [
    "generate_daily_report",
    "generate_monthly_report",
    "generate_weekly_report",
]
