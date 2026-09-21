"""当前问题事实补齐与统一状态分类。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntFlag
from typing import Any, Dict, Iterable, List, Optional, Sequence


PROBLEM_PAGE_SIZE = 1000
API_BATCH_SIZE = 200


class AttentionStatus(str, Enum):
    """面向当前问题查询的关注状态。"""

    ACTIONABLE = "actionable"
    HANDLED_ACTIVE = "handled_active"
    ENDED = "ended"
    INDETERMINATE = "indeterminate"


class LifecycleStatus(str, Enum):
    """问题事件当前可验证的生命周期状态。"""

    REAL_RECOVERED = "real_recovered"
    MANUAL_CLOSED = "manual_closed"
    STILL_TRIGGERING = "still_triggering"
    INDETERMINATE = "indeterminate"


class DispositionStatus(str, Enum):
    """问题当前有效的人工确认与人工抑制组合。"""

    UNHANDLED = "unhandled"
    ACKNOWLEDGED = "acknowledged"
    SUPPRESSED = "suppressed"
    ACKNOWLEDGED_AND_SUPPRESSED = "acknowledged_and_suppressed"


class IndeterminateReason(str, Enum):
    """原始当前问题不能进入当前仍在触发统计的原因。"""

    UNCLASSIFIED = "unclassified"
    TIMESTAMP_INVALID = "timestamp_invalid"
    TRIGGER_MISSING = "trigger_missing"
    HOST_MISSING = "host_missing"
    HOST_DISABLED = "host_disabled"
    TRIGGER_DISABLED = "trigger_disabled"
    TRIGGER_UNKNOWN = "trigger_unknown"
    ITEM_MISSING = "item_missing"
    ITEM_DISABLED = "item_disabled"
    ITEM_NOT_SUPPORTED = "item_not_supported"
    INTERFACE_ABNORMAL = "interface_abnormal"
    ACTIVE_AGENT_ABNORMAL = "active_agent_abnormal"
    RECOVERY_UNVERIFIABLE = "recovery_unverifiable"
    DISPOSITION_HISTORY_MISSING = "disposition_history_missing"
    SUPPRESSION_ORIGIN_UNKNOWN = "suppression_origin_unknown"


class ZabbixUpdateAction(IntFlag):
    """Zabbix problem update 的动作位。"""

    CLOSE = 1
    ACKNOWLEDGE = 2
    UNACKNOWLEDGE = 16
    SUPPRESS = 32
    UNSUPPRESS = 64


class IncompleteProblemDataError(RuntimeError):
    """问题事件主记录缺少完成事实分析所必需的数据。"""


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _stable_id(value: str) -> tuple[int, str]:
    return (_int(value, 0), value)


def _chunks(values: Sequence[str], size: int = API_BATCH_SIZE) -> Iterable[List[str]]:
    for offset in range(0, len(values), size):
        yield list(values[offset:offset + size])


def _current_state_start(
    updates: Sequence[Dict[str, Any]],
    set_action: ZabbixUpdateAction,
    unset_action: ZabbixUpdateAction,
    current_enabled: bool,
    start_clock: int,
    analysis_clock: int,
) -> Optional[int]:
    if not current_enabled:
        return None
    current_start: Optional[int] = None
    for update in sorted(updates, key=lambda row: _int(row.get("clock"), -1)):
        clock = _int(update.get("clock"), -1)
        if not start_clock <= clock <= analysis_clock:
            continue
        action = _int(update.get("action"), 0)
        if action & unset_action:
            current_start = None
        if action & set_action:
            current_start = clock
    return current_start


def _eventid(row: Dict[str, Any]) -> str:
    return str(row.get("eventid", ""))


def _fetch_current_problems(
    client: Any,
    hostids: Optional[Sequence[str]],
    time_from: Optional[int],
    page_size: int,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    seen: set[str] = set()
    eventid_till: Optional[str] = None

    while True:
        params: Dict[str, Any] = {
            "source": 0,
            "object": 0,
            "recent": False,
            "output": [
                "eventid", "r_eventid", "name", "severity", "clock", "objectid",
                "acknowledged", "suppressed", "userid",
            ],
            "selectAcknowledges": [
                "acknowledgeid", "userid", "clock", "action", "message", "suppress_until",
            ],
            "selectSuppressionData": ["maintenanceid", "userid", "suppress_until"],
            "sortfield": "eventid",
            "sortorder": "DESC",
            "limit": page_size,
        }
        if hostids:
            params["hostids"] = list(hostids)
        if time_from is not None:
            params["time_from"] = time_from
        if eventid_till is not None:
            params["eventid_till"] = eventid_till

        page = client.problem.get(**params)
        if not page:
            break

        page_ids: List[int] = []
        for row in page:
            row_eventid = _eventid(row)
            if not row_eventid.isdigit():
                raise RuntimeError("problem.get 返回了无效的 eventid")
            page_ids.append(int(row_eventid))
            if row_eventid not in seen:
                seen.add(row_eventid)
                rows.append(row)

        if len(page) < page_size:
            break
        next_cursor = min(page_ids) - 1
        if next_cursor < 0 or (eventid_till is not None and next_cursor >= int(eventid_till)):
            raise RuntimeError("problem.get 分页游标未前进")
        eventid_till = str(next_cursor)

    return rows


def _fetch_triggers(client: Any, triggerids: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    ordered = sorted({value for value in triggerids if value}, key=_stable_id)
    for batch in _chunks(ordered):
        rows = client.trigger.get(
            triggerids=batch,
            output=["triggerid", "description", "status", "state"],
            expandDescription=True,
            selectItems=["itemid", "status", "state", "type", "interfaceid"],
            selectHosts=["hostid", "name"],
        )
        for row in rows:
            triggerid = str(row.get("triggerid", ""))
            if triggerid:
                result[triggerid] = row
    return result


def _trigger_hostid(trigger: Dict[str, Any]) -> str:
    hosts = trigger.get("hosts") or []
    return str(hosts[0].get("hostid", "")) if hosts else ""


def _fetch_hosts(client: Any, hostids: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    ordered = sorted({value for value in hostids if value}, key=_stable_id)
    for batch in _chunks(ordered):
        rows = client.host.get(
            hostids=batch,
            output=["hostid", "host", "name", "status", "active_available"],
            selectInterfaces=[
                "interfaceid", "main", "type", "useip", "ip", "dns", "available", "error",
            ],
        )
        for row in rows:
            hostid = str(row.get("hostid", ""))
            if hostid:
                result[hostid] = row
    return result


def _fetch_recoveries(client: Any, eventids: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    ordered = sorted(
        {value for value in eventids if value and value != "0"},
        key=_stable_id,
    )
    for batch in _chunks(ordered):
        rows = client.event.get(
            eventids=batch,
            source=0,
            object=0,
            output=["eventid", "clock", "value"],
        )
        for row in rows:
            row_eventid = _eventid(row)
            if row_eventid:
                result[row_eventid] = row
    return result


def _is_manual_suppressed(row: Dict[str, Any]) -> bool:
    if str(row.get("suppressed", "0")) != "1":
        return False
    return any(
        str(item.get("maintenanceid", "")) == "0"
        and str(item.get("userid", "0")) not in {"", "0"}
        for item in (row.get("suppression_data") or [])
    )


def _is_maintenance_suppressed(row: Dict[str, Any]) -> bool:
    if str(row.get("suppressed", "0")) != "1":
        return False
    return any(
        str(item.get("maintenanceid", "0")) not in {"", "0"}
        for item in (row.get("suppression_data") or [])
    )


def _first_action_clock(
    updates: Sequence[Dict[str, Any]],
    expected_action: ZabbixUpdateAction,
    start_clock: int,
    analysis_clock: int,
) -> Optional[int]:
    clocks = [
        _int(update.get("clock"), -1)
        for update in updates
        if _int(update.get("action"), 0) & expected_action
    ]
    valid = [clock for clock in clocks if start_clock <= clock <= analysis_clock]
    return min(valid) if valid else None


def _monitoring_chain_reason(
    host: Dict[str, Any],
    trigger: Dict[str, Any],
) -> Optional[IndeterminateReason]:
    if str(host.get("status", "1")) != "0":
        return IndeterminateReason.HOST_DISABLED
    if str(trigger.get("status", "1")) != "0":
        return IndeterminateReason.TRIGGER_DISABLED
    if str(trigger.get("state", "1")) != "0":
        return IndeterminateReason.TRIGGER_UNKNOWN
    items = trigger.get("items") or []
    if not items:
        return IndeterminateReason.ITEM_MISSING
    if any(str(item.get("status", "1")) != "0" for item in items):
        return IndeterminateReason.ITEM_DISABLED
    if any(str(item.get("state", "0")) != "0" for item in items):
        return IndeterminateReason.ITEM_NOT_SUPPORTED

    interfaces = {
        str(interface.get("interfaceid", "")): interface
        for interface in (host.get("interfaces") or [])
        if interface.get("interfaceid")
    }
    for item in items:
        item_type = str(item.get("type", ""))
        interfaceid = str(item.get("interfaceid", ""))
        if item_type in {"0", "12", "16", "20"}:
            interface = interfaces.get(interfaceid)
            if interface is None or str(interface.get("available", "0")) != "1":
                return IndeterminateReason.INTERFACE_ABNORMAL
        elif item_type == "7" and str(host.get("active_available", "0")) != "1":
            return IndeterminateReason.ACTIVE_AGENT_ABNORMAL
    return None


@dataclass
class ProblemFact:
    eventid: str
    name: str
    severity: str
    start_clock: int
    triggerid: str
    hostid: str = ""
    host_name: str = "Unknown"
    attention_status: AttentionStatus = AttentionStatus.INDETERMINATE
    lifecycle_status: LifecycleStatus = LifecycleStatus.INDETERMINATE
    disposition_status: DispositionStatus = DispositionStatus.UNHANDLED
    indeterminate_reason: Optional[IndeterminateReason] = None
    r_eventid: str = "0"
    recovery_event_at: Optional[int] = None
    actual_recovered: bool = False
    actual_recovery_at: Optional[int] = None
    manual_closed: bool = False
    manual_closed_at: Optional[int] = None
    acknowledged_current: bool = False
    acknowledged_at: Optional[int] = None
    manually_suppressed_current: bool = False
    manually_suppressed_at: Optional[int] = None
    maintenance_suppressed_current: bool = False
    host_status: Optional[str] = None
    host_active_available: Optional[str] = None
    trigger_status: Optional[str] = None
    trigger_state: Optional[str] = None
    items: List[Dict[str, Any]] = field(default_factory=list)
    interfaces: List[Dict[str, Any]] = field(default_factory=list)
    action_history: List[Dict[str, Any]] = field(default_factory=list)
    suppression_data: List[Dict[str, Any]] = field(default_factory=list)
    monitoring_chain_reason: Optional[IndeterminateReason] = None


@dataclass
class ProblemStatusResult:
    analysis_clock: int
    raw_count: int
    facts: List[ProblemFact] = field(default_factory=list)

    def by_status(self, status: AttentionStatus) -> List[ProblemFact]:
        return [fact for fact in self.facts if fact.attention_status == status]


def _analyze_problem_rows(
    client: Any,
    problems: Sequence[Dict[str, Any]],
    analysis_clock: int,
) -> ProblemStatusResult:
    triggerids = [str(row.get("objectid", "")) for row in problems]
    triggers = _fetch_triggers(client, triggerids)
    hostids_to_fetch = [_trigger_hostid(row) for row in triggers.values()]
    hosts = _fetch_hosts(client, hostids_to_fetch)
    recoveries = _fetch_recoveries(
        client,
        [str(row.get("r_eventid", "0")) for row in problems],
    )

    facts: List[ProblemFact] = []
    for row in problems:
        eventid = _eventid(row)
        triggerid = str(row.get("objectid", ""))
        trigger = triggers.get(triggerid)
        hostid = _trigger_hostid(trigger or {})
        host = hosts.get(hostid)
        start_clock = _int(row.get("clock"), -1)
        updates = row.get("acknowledges") or []
        acknowledged_current = str(row.get("acknowledged", "0")) == "1"
        acknowledged_at = _current_state_start(
            updates,
            ZabbixUpdateAction.ACKNOWLEDGE,
            ZabbixUpdateAction.UNACKNOWLEDGE,
            acknowledged_current,
            start_clock,
            analysis_clock,
        )
        manually_suppressed_current = _is_manual_suppressed(row)
        manually_suppressed_at = _current_state_start(
            updates,
            ZabbixUpdateAction.SUPPRESS,
            ZabbixUpdateAction.UNSUPPRESS,
            manually_suppressed_current,
            start_clock,
            analysis_clock,
        )
        maintenance_suppressed_current = _is_maintenance_suppressed(row)
        manual_closed_at = _first_action_clock(
            updates,
            ZabbixUpdateAction.CLOSE,
            start_clock,
            analysis_clock,
        )
        manual_closed = manual_closed_at is not None

        r_eventid = str(row.get("r_eventid", "0"))
        recovery_event_at: Optional[int] = None
        actual_recovery_at: Optional[int] = None
        actual_recovered = False
        recovery_link_invalid = False
        if r_eventid != "0":
            recovery = recoveries.get(r_eventid)
            recovery_clock = _int((recovery or {}).get("clock"), -1)
            if recovery is None or str(recovery.get("value", "")) != "0":
                recovery_link_invalid = True
            elif (
                recovery_clock < 0
                or recovery_clock < start_clock
                or recovery_clock > analysis_clock
            ):
                recovery_link_invalid = True
            else:
                recovery_event_at = recovery_clock if recovery_clock >= 0 else None
                if not manual_closed:
                    actual_recovered = True
                    actual_recovery_at = recovery_event_at

        monitoring_chain_reason = (
            _monitoring_chain_reason(host, trigger)
            if host is not None and trigger is not None
            else None
        )
        suppression_origin_unknown = (
            str(row.get("suppressed", "0")) == "1"
            and not manually_suppressed_current
            and not maintenance_suppressed_current
        )

        reason: Optional[IndeterminateReason] = None
        if str(row.get("severity", "0")) == "0":
            reason = IndeterminateReason.UNCLASSIFIED
        elif start_clock < 0 or start_clock > analysis_clock:
            reason = IndeterminateReason.TIMESTAMP_INVALID
        elif not (actual_recovered or manual_closed) and recovery_link_invalid:
            reason = IndeterminateReason.RECOVERY_UNVERIFIABLE
        elif not (actual_recovered or manual_closed) and trigger is None:
            reason = IndeterminateReason.TRIGGER_MISSING
        elif not (actual_recovered or manual_closed) and host is None:
            reason = IndeterminateReason.HOST_MISSING
        elif not (actual_recovered or manual_closed):
            reason = monitoring_chain_reason

        if (
            reason is None
            and not (actual_recovered or manual_closed)
            and (
                (acknowledged_current and acknowledged_at is None)
                or (manually_suppressed_current and manually_suppressed_at is None)
            )
        ):
            reason = IndeterminateReason.DISPOSITION_HISTORY_MISSING
        if (
            reason is None
            and not (actual_recovered or manual_closed)
            and suppression_origin_unknown
        ):
            reason = IndeterminateReason.SUPPRESSION_ORIGIN_UNKNOWN

        acknowledged_effective = acknowledged_at is not None
        suppressed_effective = manually_suppressed_at is not None
        if acknowledged_effective and suppressed_effective:
            disposition_status = DispositionStatus.ACKNOWLEDGED_AND_SUPPRESSED
        elif acknowledged_effective:
            disposition_status = DispositionStatus.ACKNOWLEDGED
        elif suppressed_effective:
            disposition_status = DispositionStatus.SUPPRESSED
        else:
            disposition_status = DispositionStatus.UNHANDLED

        if reason is not None:
            attention_status = AttentionStatus.INDETERMINATE
            lifecycle_status = LifecycleStatus.INDETERMINATE
        elif actual_recovered or manual_closed:
            attention_status = AttentionStatus.ENDED
            lifecycle_status = (
                LifecycleStatus.MANUAL_CLOSED
                if manual_closed
                else LifecycleStatus.REAL_RECOVERED
            )
        elif acknowledged_at is not None or manually_suppressed_at is not None:
            attention_status = AttentionStatus.HANDLED_ACTIVE
            lifecycle_status = LifecycleStatus.STILL_TRIGGERING
        else:
            attention_status = AttentionStatus.ACTIONABLE
            lifecycle_status = LifecycleStatus.STILL_TRIGGERING

        facts.append(ProblemFact(
            eventid=eventid,
            name=str(row.get("name") or (trigger or {}).get("description") or "Unknown"),
            severity=str(row.get("severity", "0")),
            start_clock=start_clock,
            triggerid=triggerid,
            hostid=hostid,
            host_name=str((host or {}).get("name") or "Unknown"),
            attention_status=attention_status,
            lifecycle_status=lifecycle_status,
            disposition_status=disposition_status,
            indeterminate_reason=reason,
            r_eventid=r_eventid,
            recovery_event_at=recovery_event_at,
            actual_recovered=actual_recovered,
            actual_recovery_at=actual_recovery_at,
            manual_closed=manual_closed,
            manual_closed_at=manual_closed_at,
            acknowledged_current=acknowledged_current,
            acknowledged_at=acknowledged_at,
            manually_suppressed_current=manually_suppressed_current,
            manually_suppressed_at=manually_suppressed_at,
            maintenance_suppressed_current=maintenance_suppressed_current,
            host_status=str(host.get("status")) if host is not None else None,
            host_active_available=(
                str(host.get("active_available")) if host is not None else None
            ),
            trigger_status=(
                str(trigger.get("status")) if trigger is not None else None
            ),
            trigger_state=str(trigger.get("state")) if trigger is not None else None,
            items=[dict(item) for item in ((trigger or {}).get("items") or [])],
            interfaces=[dict(item) for item in ((host or {}).get("interfaces") or [])],
            action_history=[dict(item) for item in updates],
            suppression_data=[dict(item) for item in (row.get("suppression_data") or [])],
            monitoring_chain_reason=monitoring_chain_reason,
        ))

    return ProblemStatusResult(
        analysis_clock=analysis_clock,
        raw_count=len(problems),
        facts=facts,
    )


def analyze_current_problems(
    client: Any,
    analysis_clock: int,
    hostids: Optional[Sequence[str]] = None,
    time_from: Optional[int] = None,
    page_size: int = PROBLEM_PAGE_SIZE,
) -> ProblemStatusResult:
    """加载全部 Zabbix 原始当前问题并派生统一关注状态。"""
    problems = _fetch_current_problems(client, hostids, time_from, page_size)
    return _analyze_problem_rows(client, problems, analysis_clock)


def analyze_problem_events(
    client: Any,
    events: Sequence[Dict[str, Any]],
    analysis_clock: int,
) -> ProblemStatusResult:
    """补齐一组已取得的问题事件，并派生统一状态事实。"""
    return _analyze_problem_rows(client, events, analysis_clock)


def analyze_problem_event(
    client: Any,
    eventid: str,
    analysis_clock: int,
) -> Optional[ProblemFact]:
    """按问题事件 ID 加载一个可追溯的问题事实。"""
    rows = client.event.get(
        eventids=[eventid],
        source=0,
        object=0,
        value=1,
        output=[
            "eventid", "r_eventid", "name", "severity", "clock", "objectid",
            "acknowledged", "suppressed", "userid", "value",
        ],
        selectAcknowledges=[
            "acknowledgeid", "userid", "clock", "action", "message", "suppress_until",
        ],
        selectSuppressionData=["maintenanceid", "userid", "suppress_until"],
    )
    if not rows:
        return None
    if len(rows) != 1 or _eventid(rows[0]) != eventid:
        raise IncompleteProblemDataError("问题事件返回数量或事件 ID 不一致")

    row = rows[0]
    for field_name in (
        "eventid", "objectid", "clock", "severity", "value", "r_eventid",
        "acknowledged", "suppressed", "acknowledges", "suppression_data",
    ):
        if field_name not in row or row[field_name] in (None, ""):
            raise IncompleteProblemDataError(f"问题事件缺少字段 {field_name}")
    if str(row.get("value")) != "1":
        raise IncompleteProblemDataError("查询结果不是问题事件")

    result = _analyze_problem_rows(client, [row], analysis_clock)
    if len(result.facts) != 1:
        raise IncompleteProblemDataError("问题事实分析结果数量异常")
    return result.facts[0]
