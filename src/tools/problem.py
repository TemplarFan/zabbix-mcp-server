"""问题摘要与问题事实明细工具：统一分类视图与单事件全量事实。"""
import time
from datetime import datetime
from typing import Annotated, List, Optional, Union

from pydantic import Field

from client import get_zabbix_client
from utils.params import parse_int_param, parse_list_param, parse_time_param_strict
from utils.format import guard_text
from services.problem_status import (
    AttentionStatus,
    IndeterminateReason,
    IncompleteProblemDataError,
    LifecycleStatus,
    ProblemFact,
    ProblemStatusResult,
    ZabbixUpdateAction,
    analyze_current_problems,
    analyze_problem_event,
)
from ._analysis_common import (
    BEIJING_TZ,
    PROBLEM_SUMMARY_TOP_N,
    PROBLEM_VIEW_LABELS,
    PROBLEM_REASON_LABELS,
    ATTENTION_STATUS_LABELS,
    DISPOSITION_STATUS_LABELS,
    LIFECYCLE_STATUS_LABELS,
    SEVERITY_NAMES,
    SEVERITY_ORDER,
)


def _problem_detail_table(facts: List[ProblemFact], group_by: str) -> List[str]:
    if group_by == "host":
        group_key = lambda fact: fact.host_name
        ordered_keys = sorted({group_key(fact) for fact in facts})
    else:
        group_key = lambda fact: fact.severity
        ordered_keys = [
            severity for severity in SEVERITY_ORDER
            if any(group_key(fact) == severity for fact in facts)
        ]

    lines: List[str] = []
    for key in ordered_keys:
        grouped = [fact for fact in facts if group_key(fact) == key]
        label = key if group_by == "host" else SEVERITY_NAMES.get(key, key)
        lines.extend([
            f"### {label} ({len(grouped)}个)",
            "",
            "| 时间 | 主机 | 问题 | 事件ID |",
            "|---|---|---|---|",
        ])
        for fact in grouped[:PROBLEM_SUMMARY_TOP_N]:
            time_text = datetime.fromtimestamp(fact.start_clock, tz=BEIJING_TZ).strftime("%m-%d %H:%M")
            lines.append(f"| {time_text} | {fact.host_name} | {fact.name} | {fact.eventid} |")
        if len(grouped) > PROBLEM_SUMMARY_TOP_N:
            lines.append(f"\n仅展示前 {PROBLEM_SUMMARY_TOP_N} 条，本组统计共 {len(grouped)} 条。")
        lines.append("")
    return lines


def _render_problem_summary(
    summary: ProblemStatusResult,
    view: str,
    group_by: str,
    time_range: Optional[str],
) -> str:
    actionable = summary.by_status(AttentionStatus.ACTIONABLE)
    handled = summary.by_status(AttentionStatus.HANDLED_ACTIVE)
    ended = summary.by_status(AttentionStatus.ENDED)
    if time_range is None:
        range_text = "全部"
    elif str(time_range).strip().isdigit():
        range_text = f"开始时间不早于 Unix 时间戳 {str(time_range).strip()} 的"
    else:
        range_text = f"开始于最近 {str(time_range).strip().lower()} 的"
    lines = [
        f"## 当前问题摘要（{range_text} Zabbix 原始当前问题）",
        "",
        f"- Zabbix 原始当前问题: {summary.raw_count}",
        f"- 当前仍在触发: {len(actionable) + len(handled)}",
        f"  - 当前需处理: {len(actionable)}",
        f"  - 已处置但仍在触发: {len(handled)}",
        f"- 已结束: {len(ended)}",
        "",
        "### 独立事实统计",
        "",
        f"- 真实恢复: {sum(fact.actual_recovered for fact in summary.facts)}",
        f"- 人工关闭: {sum(fact.manual_closed for fact in summary.facts)}",
        f"- 当前人工确认: {sum(fact.acknowledged_current for fact in summary.facts)}",
        f"- 当前人工抑制: {sum(fact.manually_suppressed_current for fact in summary.facts)}",
        "",
    ]

    sections: List[tuple[str, List[ProblemFact]]] = []
    if view == "current":
        sections = [("当前需处理", actionable), ("已处置但仍在触发", handled)]
    elif view == "actionable":
        sections = [("当前需处理", actionable)]
    elif view == "handled_active":
        sections = [("已处置但仍在触发", handled)]
    else:
        sections = []

    for title, facts in sections:
        lines.extend([f"## {title} ({len(facts)}个)", ""])
        if title == "已处置但仍在触发" and facts:
            lines.extend(["> 这些问题已有人工确认或人工抑制，但实际未恢复。", ""])
        if not facts:
            lines.extend(["无。", ""])
            continue
        lines.extend(_problem_detail_table(facts, group_by))

    return "\n".join(lines).rstrip()


def _parse_problem_time_range(value: Optional[str], analysis_clock: int) -> Optional[int]:
    """统一时间解析（见 utils.params.parse_time_param_strict）+ 业务校验。"""
    time_from = parse_time_param_strict(value, "time_range", reference=analysis_clock)
    if time_from is not None and time_from > analysis_clock:
        raise ValueError("time_range 的开始时间不能晚于当前分析时间")
    return time_from


def _get_problem_summary_impl(client, hostids=None, time_range=None, group_by="severity", view="current"):
    if group_by not in {"severity", "host"}:
        return "获取问题摘要失败: group_by 仅支持 severity 或 host"
    if view not in PROBLEM_VIEW_LABELS:
        return "获取问题摘要失败: view 仅支持 current、actionable 或 handled_active"

    hostid_list = parse_list_param(hostids) if hostids is not None else None
    analysis_clock = int(time.time())
    try:
        time_from = _parse_problem_time_range(time_range, analysis_clock)
        summary = analyze_current_problems(
            client,
            analysis_clock=analysis_clock,
            hostids=[str(value) for value in hostid_list] if hostid_list else None,
            time_from=time_from,
        )
        return guard_text(
            _render_problem_summary(summary, view, group_by, time_range),
            hint="传入 hostids 聚焦单台主机，或用 time_range 缩小范围",
        )
    except Exception as exc:
        return f"获取问题摘要失败: {exc}"


def get_problem_summary(
    hostids: Annotated[Union[str, int, None], Field(description="主机ID（不支持主机名，需先查host_get）")] = None,
    time_range: Annotated[Optional[str], Field(description="可选时间范围；不传时查询全部原始当前问题，传入7d/24h等时只筛选开始时间")] = None,
    group_by: Annotated[str, Field(description="明细分组方式：severity或host")] = "severity",
    view: Annotated[str, Field(description="查询视图：current当前仍在触发分组、actionable当前需处理、handled_active已处置但仍触发")] = "current",
) -> str:
    """查询统一分类后的当前问题摘要。历史事件用event_get"""
    return _get_problem_summary_impl(get_zabbix_client(), hostids, time_range, group_by, view)


def _format_problem_fact_time(clock: Optional[int]) -> str:
    if clock is None:
        return "无"
    readable = datetime.fromtimestamp(clock, tz=BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")
    return f"{readable} (Unix {clock})"


def _problem_action_labels(action: int) -> str:
    labels: List[str] = []
    bit_labels = (
        (int(ZabbixUpdateAction.CLOSE), "人工关闭"),
        (int(ZabbixUpdateAction.ACKNOWLEDGE), "确认"),
        (4, "留言"),
        (8, "修改严重级别"),
        (int(ZabbixUpdateAction.UNACKNOWLEDGE), "取消确认"),
        (int(ZabbixUpdateAction.SUPPRESS), "人工抑制"),
        (int(ZabbixUpdateAction.UNSUPPRESS), "解除抑制"),
        (128, "标记为原因"),
        (256, "标记为症状"),
    )
    for bit, label in bit_labels:
        if action & bit:
            labels.append(label)
    return "、".join(labels) if labels else f"其他更新（action={action}）"


def _render_problem_fact_detail(fact: ProblemFact) -> str:
    reason = (
        PROBLEM_REASON_LABELS.get(fact.indeterminate_reason, "未知")
        if fact.indeterminate_reason is not None
        else "无"
    )
    chain_indeterminate_reasons = {
        IndeterminateReason.TRIGGER_MISSING,
        IndeterminateReason.HOST_MISSING,
        IndeterminateReason.HOST_DISABLED,
        IndeterminateReason.TRIGGER_DISABLED,
        IndeterminateReason.TRIGGER_UNKNOWN,
        IndeterminateReason.ITEM_MISSING,
        IndeterminateReason.ITEM_DISABLED,
        IndeterminateReason.ITEM_NOT_SUPPORTED,
        IndeterminateReason.INTERFACE_ABNORMAL,
        IndeterminateReason.ACTIVE_AGENT_ABNORMAL,
    }
    chain_state_reason = fact.monitoring_chain_reason
    if chain_state_reason is None and fact.indeterminate_reason in chain_indeterminate_reasons:
        chain_state_reason = fact.indeterminate_reason
    chain_reason = (
        PROBLEM_REASON_LABELS.get(chain_state_reason, "异常原因未知")
        if chain_state_reason is not None
        else "正常"
    )
    if fact.attention_status == AttentionStatus.HANDLED_ACTIVE:
        conclusion = "已处置但实际未恢复。"
    elif fact.lifecycle_status == LifecycleStatus.REAL_RECOVERED:
        conclusion = "问题已真实恢复。"
    elif fact.lifecycle_status == LifecycleStatus.MANUAL_CLOSED:
        conclusion = "问题已人工关闭，不能视为自动恢复。"
    elif fact.attention_status == AttentionStatus.ACTIONABLE:
        conclusion = "问题仍在触发且当前需要处理。"
    else:
        conclusion = f"当前无法可靠判定，原因：{reason}。"

    lines = [
        f"## 问题事件 {fact.eventid} 事实明细",
        "",
        "### 基本信息",
        "",
        f"- 问题: {fact.name}",
        f"- 主机: {fact.host_name}",
        f"- 主机ID: {fact.hostid or '无法归属'}",
        f"- 触发器ID: {fact.triggerid or '缺失'}",
        f"- 阈值表达式: {fact.trigger_expression or '无法获取（触发器缺失或不可见）'}",
    ]
    if fact.trigger_recovery_expression:
        lines.append(f"- 恢复表达式: {fact.trigger_recovery_expression}")
    lines.extend([
        f"- 严重级别: {fact.severity}",
        f"- 发生时间: {_format_problem_fact_time(fact.start_clock)}",
        "",
        "### 派生状态",
        "",
        f"- 生命周期: {LIFECYCLE_STATUS_LABELS[fact.lifecycle_status]}",
        f"- 人工处置: {DISPOSITION_STATUS_LABELS[fact.disposition_status]}",
        f"- 关注状态: {ATTENTION_STATUS_LABELS[fact.attention_status]}",
        f"- 不可判定原因: {reason}",
        "",
        "### 独立事实与时间",
        "",
        f"- 真实恢复: {'是' if fact.actual_recovered else '否'}",
        f"- 真实恢复时间: {_format_problem_fact_time(fact.actual_recovery_at)}",
        f"- 恢复事件ID: {fact.r_eventid if fact.r_eventid != '0' else '无'}",
        f"- 人工关闭: {'是' if fact.manual_closed else '否'}",
        f"- 人工关闭时间: {_format_problem_fact_time(fact.manual_closed_at)}",
        f"- 当前人工确认: {'是' if fact.acknowledged_current else '否'}",
        f"- 当前确认起始时间: {_format_problem_fact_time(fact.acknowledged_at)}",
        f"- 当前人工抑制: {'是' if fact.manually_suppressed_current else '否'}",
        f"- 当前人工抑制起始时间: {_format_problem_fact_time(fact.manually_suppressed_at)}",
        f"- 当前维护期抑制: {'是' if fact.maintenance_suppressed_current else '否'}",
        "",
        "### 人工处置时间线",
        "",
    ])
    if fact.action_history:
        for update in sorted(
            fact.action_history,
            key=lambda row: parse_int_param(row.get("clock"), -1) or -1,
        ):
            clock = parse_int_param(update.get("clock"))
            action = parse_int_param(update.get("action"), 0) or 0
            user = str(update.get("userid", "0"))
            message = str(update.get("message") or "").strip()
            line = (
                f"- {_format_problem_fact_time(clock)}: "
                f"{_problem_action_labels(action)}（用户ID {user}）"
            )
            if message:
                line += f"；说明: {message}"
            lines.append(line)
    else:
        lines.append("无人工处置记录。")

    lines.extend([
        "",
        "### 当前监控链路",
        "",
        f"- 当前监控链路判定: {chain_reason}",
        f"- 主机状态: {fact.host_status if fact.host_status is not None else '未知'}",
        f"- 主动 Agent 可用性: {fact.host_active_available if fact.host_active_available is not None else '未知'}",
        f"- 触发器状态: {fact.trigger_status if fact.trigger_status is not None else '未知'}",
        f"- 触发器运行状态: {fact.trigger_state if fact.trigger_state is not None else '未知'}",
        f"- 关联监控项: {len(fact.items)} 个",
    ])
    for item in fact.items:
        status_label = "已启用" if str(item.get("status", "1")) == "0" else "已停用"
        lines.append(
            f"  - itemid={item.get('itemid')} key_={item.get('key_', '未知')}（{status_label}）"
        )
    lines.extend([
        f"- 关联接口数: {len(fact.interfaces)}",
        "",
        f"**结论: {conclusion}**",
    ])
    return "\n".join(lines)


def _get_problem_fact_detail_impl(client, eventid):
    normalized_eventid = str(eventid).strip()
    if not normalized_eventid.isdigit() or int(normalized_eventid) <= 0:
        return "查询具体问题失败: eventid 必须是正整数"

    try:
        fact = analyze_problem_event(
            client,
            normalized_eventid,
            analysis_clock=int(time.time()),
        )
    except IncompleteProblemDataError as exc:
        return f"查询具体问题不完整: {exc}"
    except Exception as exc:
        return f"查询具体问题失败: {exc}"

    if fact is None:
        return f"未找到问题事件: {normalized_eventid}"
    return guard_text(_render_problem_fact_detail(fact))


def get_problem_fact_detail(
    eventid: Annotated[Union[str, int], Field(description="问题事件ID（不是触发器ID）")],
) -> str:
    """按问题事件 ID 查询真实恢复、人工处置和当前监控状态。"""
    return _get_problem_fact_detail_impl(get_zabbix_client(), eventid)


