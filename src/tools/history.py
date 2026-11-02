"""主机告警历史工具：完整分页、精确恢复配对与独立事实时间线。"""
import time
from datetime import datetime
from typing import Annotated, Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field

from client import get_zabbix_client
from config import BEFORE_WINDOW_HOURS, DEFAULT_QUERY_DAYS
from services.event_paginator import fetch_all_eventid_pages
from services.problem_status import (
    ProblemFact,
    analyze_problem_events,
)
from utils.format import format_response
from utils.params import parse_int_param, parse_list_param, parse_time_param_strict
from ._analysis_common import (
    BEIJING_TZ,
    DISPOSITION_STATUS_LABELS,
    LIFECYCLE_STATUS_LABELS,
    PROBLEM_REASON_LABELS,
    QUICK_STATUS_PAGE_SIZE,
)


# history_get 与 event_get 共用的返回条数上限（event.py 跨模块引用）
HISTORY_MAX_LIMIT = 500


def _fetch_eventid_pages(
    endpoint: Any,
    base_params: Dict[str, Any],
    page_size: int = QUICK_STATUS_PAGE_SIZE,
) -> List[Dict[str, Any]]:
    """按 eventid 游标获取完整结果，避免固定 limit 截断统计。"""
    return fetch_all_eventid_pages(endpoint, base_params, page_size)


# ===== host_alert_history 返回类型定义 =====

class AlertTimeline(BaseModel):
    """单条告警记录"""
    eventid: str = Field(description="问题事件ID")
    start_time: str = Field(description="告警开始时间（格式：YYYY-MM-DD HH:MM）")
    lifecycle_status: str = Field(description="真实恢复、人工关闭、仍在触发或不可判定")
    disposition_status: str = Field(description="当前人工处置状态")
    actual_recovery_time: Optional[str] = Field(default=None, description="真实恢复时间")
    manual_closed_time: Optional[str] = Field(default=None, description="人工关闭时间")
    acknowledged_time: Optional[str] = Field(default=None, description="当前确认起始时间")
    manually_suppressed_time: Optional[str] = Field(default=None, description="当前人工抑制起始时间")
    maintenance_suppressed: bool = Field(description="当前是否为维护期抑制")
    duration_seconds: Optional[int] = Field(description="持续时间（秒），null表示无可信结束时间")
    duration_valid: bool = Field(description="持续时间是否可用于统计")
    duration_invalid_reason: Optional[str] = Field(default=None, description="持续时间无效原因")


class AlertBefore(BaseModel):
    """前置告警记录"""
    trigger_name: str = Field(description="触发器名称")
    triggerid: str = Field(description="触发器ID")
    start_time: str = Field(description="告警开始时间")
    duration_seconds: Optional[int] = Field(description="持续时间（秒），null表示未恢复")
    lifecycle_status: str = Field(description="问题生命周期状态")
    disposition_status: str = Field(description="当前人工处置状态")
    time_diff_seconds: int = Field(description="与当前告警的时间差（秒），负数表示在前")


class TriggerStats(BaseModel):
    """触发器统计数据"""
    name: str = Field(description="触发器名称")
    triggerid: str = Field(description="触发器ID")
    count: int = Field(description="告警次数")
    days_count: int = Field(description="出现在几天")
    avg_duration_seconds: Optional[float] = Field(description="平均持续时间（秒）")
    max_duration_seconds: Optional[int] = Field(description="最大持续时间（秒）")
    min_duration_seconds: Optional[int] = Field(description="最小持续时间（秒）")
    slot_distribution: Dict[str, int] = Field(description="时段分布")
    daily_distribution: Dict[str, int] = Field(description="每天告警次数")
    timeline: List[AlertTimeline] = Field(description="告警时间线")


class HostSummary(BaseModel):
    """主机概览"""
    total_alerts: int = Field(description="查询期间主机所有告警数")
    trigger_types: int = Field(description="不同触发器数量")


class HostAlertHistoryResult(BaseModel):
    """host_alert_history 工具返回结果"""
    complete: bool = Field(description="查询及补齐是否完整")
    error: Optional[str] = Field(default=None, description="查询失败原因")
    host_summary: HostSummary = Field(description="主机概览（查询期间主机所有告警统计）")
    trigger_stats: TriggerStats = Field(description="当前触发器统计（历史告警分析）")
    alerts_before: List[AlertBefore] = Field(description="当前告警前的其他告警（可能关联）")


def _history_problem_query_params(
    hostid: str,
    time_from: int,
    time_till: int,
    triggerid: Optional[str] = None,
) -> Dict[str, Any]:
    params: Dict[str, Any] = {
        "hostids": [hostid],
        "source": 0,
        "object": 0,
        "value": 1,
        "time_from": time_from,
        "time_till": time_till,
        "output": [
            "eventid", "r_eventid", "name", "severity", "clock", "objectid",
            "acknowledged", "suppressed", "userid", "value",
        ],
        "selectAcknowledges": [
            "acknowledgeid", "userid", "clock", "action", "message", "suppress_until",
        ],
        "selectSuppressionData": ["maintenanceid", "userid", "suppress_until"],
    }
    if triggerid is not None:
        params["objectids"] = [triggerid]
    return params


def _history_time_text(clock: Optional[int]) -> Optional[str]:
    if clock is None:
        return None
    return datetime.fromtimestamp(clock, tz=BEIJING_TZ).strftime("%Y-%m-%d %H:%M")


def _history_duration(fact: ProblemFact) -> tuple[Optional[int], bool, Optional[str]]:
    end_clock = fact.actual_recovery_at or fact.manual_closed_at
    if end_clock is None:
        reason = (
            PROBLEM_REASON_LABELS.get(fact.indeterminate_reason, "不可判定")
            if fact.indeterminate_reason is not None
            else "尚无可信结束时间"
        )
        return None, False, reason
    if fact.start_clock < 0 or end_clock < fact.start_clock:
        return None, False, "结束时间早于问题时间或时间戳无效"
    return end_clock - fact.start_clock, True, None


def _history_timeline(fact: ProblemFact) -> AlertTimeline:
    duration, duration_valid, invalid_reason = _history_duration(fact)
    start_time = _history_time_text(fact.start_clock) if fact.start_clock >= 0 else None
    return AlertTimeline(
        eventid=fact.eventid,
        start_time=start_time or f"无效时间 (Unix {fact.start_clock})",
        lifecycle_status=LIFECYCLE_STATUS_LABELS[fact.lifecycle_status],
        disposition_status=DISPOSITION_STATUS_LABELS[fact.disposition_status],
        actual_recovery_time=_history_time_text(fact.actual_recovery_at),
        manual_closed_time=_history_time_text(fact.manual_closed_at),
        acknowledged_time=_history_time_text(fact.acknowledged_at),
        manually_suppressed_time=_history_time_text(fact.manually_suppressed_at),
        maintenance_suppressed=fact.maintenance_suppressed_current,
        duration_seconds=duration,
        duration_valid=duration_valid,
        duration_invalid_reason=invalid_reason,
    )


def _empty_host_alert_history(
    triggerid: str,
    *,
    complete: bool,
    error: Optional[str] = None,
) -> HostAlertHistoryResult:
    return HostAlertHistoryResult(
        complete=complete,
        error=error,
        host_summary=HostSummary(total_alerts=0, trigger_types=0),
        trigger_stats=TriggerStats(
            name="Unknown" if complete else "Error",
            triggerid=triggerid,
            count=0,
            days_count=0,
            avg_duration_seconds=None,
            max_duration_seconds=None,
            min_duration_seconds=None,
            slot_distribution={},
            daily_distribution={},
            timeline=[],
        ),
        alerts_before=[],
    )


def _host_alert_history_impl(client, hostid, triggerid, days=DEFAULT_QUERY_DAYS):
    """查询完整分页、精确恢复配对的主机与触发器告警历史。"""
    normalized_hostid = str(hostid)
    normalized_triggerid = str(triggerid)
    if days <= 0:
        return _empty_host_alert_history(
            normalized_triggerid,
            complete=False,
            error="days 必须大于 0",
        )

    analysis_clock = int(time.time())
    time_from = analysis_clock - days * 86400
    try:
        trigger_events = _fetch_eventid_pages(
            client.event,
            _history_problem_query_params(
                normalized_hostid,
                time_from,
                analysis_clock,
                normalized_triggerid,
            ),
        )
        host_events = _fetch_eventid_pages(
            client.event,
            _history_problem_query_params(
                normalized_hostid,
                time_from,
                analysis_clock,
            ),
        )

        trigger_eventids = {str(row.get("eventid", "")) for row in trigger_events}
        host_eventids = {str(row.get("eventid", "")) for row in host_events}
        if not trigger_eventids.issubset(host_eventids):
            raise RuntimeError("主机事件集合缺少触发器查询已返回的问题事件")

        unique_events: Dict[str, Dict[str, Any]] = {}
        for row in [*host_events, *trigger_events]:
            eventid = str(row.get("eventid", ""))
            if eventid:
                unique_events[eventid] = row
        fact_result = analyze_problem_events(
            client,
            list(unique_events.values()),
            analysis_clock,
        )
    except Exception as exc:
        return _empty_host_alert_history(
            normalized_triggerid,
            complete=False,
            error=str(exc),
        )

    facts = {fact.eventid: fact for fact in fact_result.facts}
    trigger_facts = sorted(
        [facts[eventid] for eventid in trigger_eventids if eventid in facts],
        key=lambda fact: (fact.start_clock, int(fact.eventid)),
    )
    host_facts = [facts[eventid] for eventid in host_eventids if eventid in facts]

    slots = ["凌晨(0-6)", "上午(6-12)", "下午(12-18)", "夜晚(18-24)"]
    slot_distribution = {slot: 0 for slot in slots}
    daily_distribution: Dict[str, int] = {}
    valid_days: set[str] = set()
    valid_durations: List[int] = []
    for fact in trigger_facts:
        duration, valid, _ = _history_duration(fact)
        if valid and duration is not None:
            valid_durations.append(duration)
        if not 0 <= fact.start_clock <= analysis_clock:
            continue
        start = datetime.fromtimestamp(fact.start_clock, tz=BEIJING_TZ)
        day = start.strftime("%Y-%m-%d")
        hour = start.hour
        slot = slots[0] if hour < 6 else slots[1] if hour < 12 else slots[2] if hour < 18 else slots[3]
        valid_days.add(day)
        slot_distribution[slot] += 1
        daily_distribution[day] = daily_distribution.get(day, 0) + 1

    trigger_name = trigger_facts[-1].name if trigger_facts else "Unknown"
    valid_trigger_clocks = [
        fact.start_clock for fact in trigger_facts
        if 0 <= fact.start_clock <= analysis_clock
    ]
    current_alert_time = max(valid_trigger_clocks) if valid_trigger_clocks else analysis_clock
    before_time = current_alert_time - BEFORE_WINDOW_HOURS * 3600
    alerts_before: List[AlertBefore] = []
    for fact in sorted(host_facts, key=lambda item: (item.start_clock, int(item.eventid))):
        if fact.triggerid == normalized_triggerid:
            continue
        if not before_time <= fact.start_clock < current_alert_time:
            continue
        duration, valid, _ = _history_duration(fact)
        alerts_before.append(AlertBefore(
            trigger_name=fact.name,
            triggerid=fact.triggerid,
            start_time=_history_time_text(fact.start_clock) or "无效时间",
            duration_seconds=duration if valid else None,
            lifecycle_status=LIFECYCLE_STATUS_LABELS[fact.lifecycle_status],
            disposition_status=DISPOSITION_STATUS_LABELS[fact.disposition_status],
            time_diff_seconds=fact.start_clock - current_alert_time,
        ))

    return HostAlertHistoryResult(
        complete=True,
        error=None,
        host_summary=HostSummary(
            total_alerts=len(host_eventids),
            trigger_types=len({fact.triggerid for fact in host_facts}),
        ),
        trigger_stats=TriggerStats(
            name=trigger_name,
            triggerid=normalized_triggerid,
            count=len(trigger_eventids),
            days_count=len(valid_days),
            avg_duration_seconds=(
                round(sum(valid_durations) / len(valid_durations), 1)
                if valid_durations else None
            ),
            max_duration_seconds=max(valid_durations) if valid_durations else None,
            min_duration_seconds=min(valid_durations) if valid_durations else None,
            slot_distribution=slot_distribution,
            daily_distribution=daily_distribution,
            timeline=[_history_timeline(fact) for fact in trigger_facts],
        ),
        alerts_before=alerts_before,
    )


def host_alert_history(
    hostid: Annotated[Union[str, int], Field(description="主机ID")],
    triggerid: Annotated[Union[str, int], Field(description="触发器ID")],
    days: Annotated[int, Field(description=f"查询天数（默认{DEFAULT_QUERY_DAYS}）")] = DEFAULT_QUERY_DAYS,
) -> HostAlertHistoryResult:
    """查询完整分页、精确恢复配对的主机与触发器告警历史。"""
    return _host_alert_history_impl(get_zabbix_client(), hostid, triggerid, days)


def _history_get_impl(client, itemids, history=0, time_from=None, time_till=None, limit=None, sortfield="clock", sortorder="DESC"):
    """获取监控项原始历史数据。长期趋势用trend_get"""
    # Parse parameters
    itemids = parse_list_param(itemids)
    history = parse_int_param(history)
    limit = parse_int_param(limit, 10)
    # 严格解析：无效时间格式直接报参数错误，避免静默丢弃导致全量扫描
    try:
        time_from = parse_time_param_strict(time_from, "time_from")
        time_till = parse_time_param_strict(time_till, "time_till")
    except ValueError as exc:
        return f"参数错误: {exc}"

    # 入口护栏：单次返回条数上限，超过提示分段查询
    if limit is not None and (limit > HISTORY_MAX_LIMIT or limit <= 0):
        return (
            f"参数错误: limit 最大 {HISTORY_MAX_LIMIT}，请配合 time_from/time_till "
            "缩小时间范围或分批查询"
        )

    # 时间戳合理性检查：如果 time_from 是过去超过7天的时间戳，提示使用相对时间
    current_time = int(time.time())
    if time_from and (current_time - time_from) > (7 * 24 * 3600):
        return "错误：time_from 时间戳太老（超过7天前），可能是手动计算错误。\n" \
               "请使用相对时间格式：time_from='2h'（最近2小时）、time_from='24h'（最近24小时）、time_from='7d'（最近7天）\n" \
               "系统会自动计算正确的时间戳。"

    # 无时间下限时默认最近24小时，避免全量拉取
    default_window = False
    if time_from is None:
        time_from = current_time - 86400
        default_window = True

    params = {
        "itemids": itemids,
        "history": history,
        "sortfield": sortfield,
        "sortorder": sortorder
    }

    if time_from:
        params["time_from"] = time_from
    if time_till:
        params["time_till"] = time_till
    if limit:
        params["limit"] = limit

    result = client.history.get(**params)
    output = format_response(result)
    if default_window:
        output += "\n/* 注: 未指定 time_from，默认查询最近24小时；需要更长范围请显式传入 */\n"
    return output


def history_get(
    itemids: Annotated[Union[List[Any], str, int], Field(description="监控项ID（必填）")],
    history: Annotated[Union[int, str], Field(description="数据类型（0float/1char/2log/3uint/4text）")] = 0,
    time_from: Annotated[Union[int, str, None], Field(description="起始时间（支持相对时间如7d/24h）")] = None,
    time_till: Annotated[Union[int, str, None], Field(description="截止时间")] = None,
    limit: Annotated[Union[int, str, None], Field(description="返回条数（默认10）")] = None,
    sortfield: Annotated[str, Field(description="排序字段（默认clock）")] = "clock",
    sortorder: Annotated[str, Field(description="排序方向（DESC/ASC）")] = "DESC"
) -> str:
    """获取监控项原始历史数据。长期趋势用trend_get"""
    return _history_get_impl(get_zabbix_client(), itemids, history, time_from, time_till, limit, sortfield, sortorder)
