"""Analysis Tools - 兼容转发壳。

原单文件已按领域拆分为 trend / problem / health / history 四个模块，
共享常量在 _analysis_common。本模块仅保留既有导入路径的转发
（工具函数、Pydantic 返回类型与标签常量），不承载实现。
"""

from ._analysis_common import (  # noqa: F401
    ATTENTION_STATUS_LABELS,
    BEIJING_TZ,
    DISPOSITION_STATUS_LABELS,
    LIFECYCLE_STATUS_LABELS,
    PROBLEM_REASON_LABELS,
    PROBLEM_SUMMARY_TOP_N,
    PROBLEM_VIEW_LABELS,
    QUICK_STATUS_PAGE_SIZE,
    SEVERITY_ICONS,
    SEVERITY_NAMES,
    SEVERITY_ORDER,
)
from .health import check_host_health, quick_status  # noqa: F401
from .history import (  # noqa: F401
    AlertBefore,
    AlertTimeline,
    HostAlertHistoryResult,
    HostSummary,
    TriggerStats,
    host_alert_history,
)
from .problem import get_problem_fact_detail, get_problem_summary  # noqa: F401
from .trend import (  # noqa: F401
    TrendChange,
    TrendCoverage,
    TrendStats,
    TrendSummaryErrorResponse,
    TrendSummaryResult,
    TrendVolatility,
    trend_get,
    trend_summary,
)
