"""非报表分析工具的共享常量与标签。

四个领域模块（trend/problem/health/history）共同使用的
严重级别表、状态标签和时间常量集中于此，避免多处复制。
"""

from datetime import timezone, timedelta
from typing import Dict

from services.problem_status import (
    AttentionStatus,
    DispositionStatus,
    IndeterminateReason,
    LifecycleStatus,
)

BEIJING_TZ = timezone(timedelta(hours=8))

# 问题摘要明细每组默认展示条数（只限明细，统计总数不受影响）
PROBLEM_SUMMARY_TOP_N = 20

SEVERITY_NAMES: Dict[str, str] = {
    "5": "灾难", "4": "严重", "3": "一般", "2": "警告", "1": "信息", "0": "未分类",
}
SEVERITY_ICONS: Dict[str, str] = {
    "5": "🚨", "4": "🔴", "3": "🟠", "2": "🟡", "1": "🔵", "0": "⚪",
}
SEVERITY_ORDER = ["5", "4", "3", "2", "1", "0"]

PROBLEM_VIEW_LABELS = {
    "current": "当前仍在触发",
    "actionable": "当前需处理",
    "handled_active": "已处置但仍在触发",
}

PROBLEM_REASON_LABELS = {
    IndeterminateReason.UNCLASSIFIED: "未分类事件",
    IndeterminateReason.TIMESTAMP_INVALID: "问题时间异常",
    IndeterminateReason.TRIGGER_MISSING: "触发器缺失或已删除",
    IndeterminateReason.HOST_MISSING: "主机缺失或无法归属",
    IndeterminateReason.HOST_DISABLED: "主机当前停用",
    IndeterminateReason.TRIGGER_DISABLED: "触发器当前禁用",
    IndeterminateReason.TRIGGER_UNKNOWN: "触发器当前状态未知",
    IndeterminateReason.ITEM_MISSING: "关联监控项缺失",
    IndeterminateReason.ITEM_DISABLED: "关联监控项当前禁用",
    IndeterminateReason.ITEM_NOT_SUPPORTED: "关联监控项当前不受支持",
    IndeterminateReason.INTERFACE_ABNORMAL: "相关监控接口当前不可用或未知",
    IndeterminateReason.ACTIVE_AGENT_ABNORMAL: "主动 Agent 当前不可用或未知",
    IndeterminateReason.RECOVERY_UNVERIFIABLE: "恢复事件关联异常",
    IndeterminateReason.DISPOSITION_HISTORY_MISSING: "当前人工处置缺少有效动作记录",
    IndeterminateReason.SUPPRESSION_ORIGIN_UNKNOWN: "当前抑制来源无法判定",
}

ATTENTION_STATUS_LABELS = {
    AttentionStatus.ACTIONABLE: "当前需处理",
    AttentionStatus.HANDLED_ACTIVE: "已处置但仍在触发",
    AttentionStatus.ENDED: "已结束",
    AttentionStatus.INDETERMINATE: "不可判定",
}

LIFECYCLE_STATUS_LABELS = {
    LifecycleStatus.REAL_RECOVERED: "真实恢复",
    LifecycleStatus.MANUAL_CLOSED: "人工关闭",
    LifecycleStatus.STILL_TRIGGERING: "仍在触发",
    LifecycleStatus.INDETERMINATE: "不可判定",
}

DISPOSITION_STATUS_LABELS = {
    DispositionStatus.UNHANDLED: "未处置",
    DispositionStatus.ACKNOWLEDGED: "已确认",
    DispositionStatus.SUPPRESSED: "已人工抑制",
    DispositionStatus.ACKNOWLEDGED_AND_SUPPRESSED: "已确认且已人工抑制",
}
