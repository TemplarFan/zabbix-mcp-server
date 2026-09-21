"""MCP Zabbix 运维周报：查询、分析并生成 Markdown。"""

from __future__ import annotations

import ipaddress
import logging
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from config import TEST_NETWORKS_ENV_VAR, get_test_host_networks
from ._client import ZabbixCallClient

# ============ 基础常量 ============
BEIJING_TZ = timezone(timedelta(hours=8))
REPORT_VERSION = "v3.0"

SEVERITY_NAMES = {"5": "灾难", "4": "严重", "3": "一般", "2": "警告", "1": "信息"}
SEVERITY_EMOJIS = {"5": "🚨", "4": "🔴", "3": "🟠", "2": "🟡", "1": "🔵"}
SEVERITY_ORDER = ["5", "4", "3", "2", "1"]

EVENT_PAGE_SIZE = 1000
API_BATCH_SIZE = 500

# ============ 测试网段排除 ============
# 测试网段通过环境变量 ZABBIX_TEST_NETWORKS 配置（逗号分隔 CIDR），
# 生产口径统计时排除命中主机，未配置则不排除。

# ============ 章节展示数量参数 ============
# 统一语义：>0 展示 Top N；0 跳过整个对应章节；-1 全部展示。

# 控制“高频报警主机”章节
TOP_N_HIGH_FREQUENCY_HOSTS = 15

# 控制“规律型问题”章节
TOP_N_REGULAR_PROBLEMS = 10

# 控制“短时恢复型问题”章节
TOP_N_SHORT_RECOVERY_PROBLEMS = 5

# 控制“持续型问题”章节
TOP_N_CHRONIC_PROBLEMS = 10

# 控制“严重事件”中的“灾难”子章节
TOP_N_DISASTER_EVENTS = -1

# 控制“严重事件”中的“严重”子章节
TOP_N_SEVERE_EVENTS = -1


# ============ 分析阈值 ============
REGULAR_MIN_EVENTS = 3
REGULAR_MIN_SEGMENTS = 3
REGULAR_CONCENTRATION_RATIO = 0.60

ADAPTIVE_THRESHOLD_MIN_SAMPLES = 20
SHORT_RECOVERY_MIN_RECOVERED_EVENTS = 3
SHORT_RECOVERY_THRESHOLD_SECONDS = 180

CHRONIC_PERCENTILE = 0.90
CHRONIC_MIN_SECONDS = 3600
CHRONIC_FALLBACK_SECONDS = 3600

# 调试日志候选值：只帮助比较阈值和展示数量，不改变正式统计口径。
DIAGNOSTIC_DURATION_PERCENTILES = (0.25, 0.50, 0.75, 0.90, 0.95, 0.99)
DIAGNOSTIC_CHRONIC_THRESHOLDS = (3600, 7200, 14400, 28800, 43200, 86400)
DIAGNOSTIC_SHORT_THRESHOLDS = (60, 90, 120, 180, 300)
DIAGNOSTIC_REGULAR_RATIOS = (0.50, 0.60, 0.70, 0.80)
DIAGNOSTIC_TOP_LIMITS = (5, 10, 15, 20)

logger = logging.getLogger(__name__)

def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _optional_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _stable_id(value: str) -> Tuple[int, str]:
    """数字 ID 按数值排序，异常 ID 仍能稳定排序。"""
    try:
        return 0, f"{int(value):020d}"
    except (TypeError, ValueError):
        return 1, str(value)


def _chunks(values: Sequence[str], size: int = API_BATCH_SIZE) -> Iterable[List[str]]:
    for index in range(0, len(values), size):
        yield list(values[index:index + size])


def calc_percentile(values: Sequence[int], percentile: float) -> int:
    """使用线性插值计算百分位数，结果四舍五入到秒。"""
    if not values:
        return 0
    ordered = sorted(values)
    if len(ordered) == 1:
        return int(ordered[0])
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return int(ordered[lower])
    weight = position - lower
    return int(round(ordered[lower] * (1 - weight) + ordered[upper] * weight))


def format_duration(seconds: int | float) -> str:
    seconds = max(0, int(round(seconds)))
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)
    parts: List[str] = []
    if days:
        parts.append(f"{days}天")
    if hours:
        parts.append(f"{hours}小时")
    if minutes:
        parts.append(f"{minutes}分")
    if secs or not parts:
        parts.append(f"{secs}秒")
    return "".join(parts)


def format_optional_duration(seconds: Optional[int | float], unavailable: str = "无有效时长") -> str:
    return unavailable if seconds is None else format_duration(seconds)


def get_time_slot(clock: int) -> str:
    hour = datetime.fromtimestamp(clock, tz=BEIJING_TZ).hour
    start = hour // 4 * 4
    return f"{start:02d}-{start + 4:02d}"


def build_week_segments(week_start: datetime, week_end: datetime) -> List[Dict[str, Any]]:
    """把自然周切分为周一至周日七个自然日。"""
    if week_start.tzinfo is None or week_end.tzinfo is None:
        raise ValueError("week_start and week_end must be timezone-aware")
    if week_end - week_start != timedelta(days=7) or week_start.weekday() != 0:
        raise ValueError("weekly range must be a Monday-based seven-day period")
    labels = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    segments = []
    for index, label in enumerate(labels):
        start = week_start + timedelta(days=index)
        end = start + timedelta(days=1)
        segments.append({
            "key": f"D{index + 1}",
            "label": label,
            "start": int(start.timestamp()),
            "end": int(end.timestamp()),
            "range": start.strftime("%Y-%m-%d"),
            "is_full_week": False,
        })
    return segments


def get_week_range(
    date: str = "last_week",
    now: Optional[datetime] = None,
) -> Tuple[int, int, str, str, List[Dict[str, Any]]]:
    now = now or datetime.now(BEIJING_TZ)
    if now.tzinfo is None:
        now = now.replace(tzinfo=BEIJING_TZ)
    else:
        now = now.astimezone(BEIJING_TZ)

    if date == "last_week":
        current_monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = current_monday - timedelta(days=7)
    else:
        try:
            selected = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=BEIJING_TZ)
        except ValueError as exc:
            raise ValueError("date must be 'last_week' or YYYY-MM-DD") from exc
        week_start = selected - timedelta(days=selected.weekday())
    week_end = week_start + timedelta(days=7)

    segments = build_week_segments(week_start, week_end)
    return (
        int(week_start.timestamp()),
        int(week_end.timestamp()),
        week_start.strftime("%Y-%m-%d"),
        (week_end - timedelta(days=1)).strftime("%Y-%m-%d"),
        segments,
    )


def fetch_problem_events(
    client: ZabbixCallClient,
    time_from: int,
    time_till: int,
    page_size: int = EVENT_PAGE_SIZE,
) -> List[Dict[str, Any]]:
    """按 eventid 游标稳定分页，只查询指定自然周内的问题事件。"""
    if page_size <= 0:
        raise ValueError("page_size must be positive")

    events: List[Dict[str, Any]] = []
    seen: set[str] = set()
    eventid_till: Optional[str] = None

    while True:
        params: Dict[str, Any] = {
            "source": 0,
            "object": 0,
            "value": 1,
            "time_from": time_from,
            "time_till": time_till - 1,
            "output": [
                "eventid", "r_eventid", "name", "severity", "clock", "objectid", "value",
                "acknowledged", "suppressed", "userid", "c_eventid", "correlationid",
            ],
            "selectHosts": ["hostid", "name"],
            "selectAcknowledges": ["acknowledgeid", "userid", "clock", "action", "suppress_until"],
            "selectSuppressionData": ["maintenanceid", "userid", "suppress_until"],
            "sortfield": "eventid",
            "sortorder": "DESC",
            "limit": page_size,
        }
        if eventid_till is not None:
            params["eventid_till"] = eventid_till

        page = client.call("event.get", params)
        if not page:
            break

        page_ids: List[int] = []
        for row in page:
            eventid = str(row.get("eventid", ""))
            if not eventid or not eventid.isdigit():
                raise RuntimeError("event.get returned an invalid eventid")
            page_ids.append(int(eventid))
            if eventid not in seen:
                seen.add(eventid)
                events.append(row)

        if len(page) < page_size:
            break
        next_cursor = min(page_ids) - 1
        if next_cursor < 0 or (eventid_till is not None and next_cursor >= int(eventid_till)):
            raise RuntimeError("event.get pagination cursor did not advance")
        eventid_till = str(next_cursor)

    return events


def fetch_current_hosts(client: ZabbixCallClient, hostids: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    ordered_ids = sorted({str(value) for value in hostids if value}, key=_stable_id)
    for batch in _chunks(ordered_ids):
        rows = client.call("host.get", {
            "hostids": batch,
            "output": ["hostid", "host", "name", "status", "active_available"],
            "selectInterfaces": ["interfaceid", "main", "type", "useip", "ip", "dns", "available", "error"],
        })
        for row in rows:
            hostid = str(row.get("hostid", ""))
            if hostid:
                result[hostid] = row
    return result


def fetch_current_triggers(client: ZabbixCallClient, triggerids: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    ordered_ids = sorted({str(value) for value in triggerids if value}, key=_stable_id)
    for batch in _chunks(ordered_ids):
        rows = client.call("trigger.get", {
            "triggerids": batch,
            "output": ["triggerid", "description", "status", "state"],
            "expandDescription": True,
            "selectItems": ["itemid", "status", "state", "type", "interfaceid"],
            "selectHosts": ["hostid", "name"],
        })
        for row in rows:
            triggerid = str(row.get("triggerid", ""))
            if triggerid:
                result[triggerid] = row
    return result


def fetch_recovery_events(client: ZabbixCallClient, eventids: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    ordered_ids = sorted({str(value) for value in eventids if value and str(value) != "0"}, key=_stable_id)
    for batch in _chunks(ordered_ids):
        rows = client.call("event.get", {
            "eventids": batch,
            "source": 0,
            "object": 0,
            "output": ["eventid", "clock", "value"],
        })
        for row in rows:
            eventid = str(row.get("eventid", ""))
            if eventid:
                result[eventid] = row
    return result


def _event_hostid(event_row: Dict[str, Any]) -> str:
    hosts = event_row.get("hosts") or []
    if not hosts:
        return ""
    return str(hosts[0].get("hostid", ""))


def _trigger_hostid(trigger_row: Dict[str, Any]) -> str:
    hosts = trigger_row.get("hosts") or []
    if not hosts:
        return ""
    return str(hosts[0].get("hostid", ""))


def _segment_for_clock(clock: int, segments: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for segment in segments:
        if int(segment["start"]) <= clock < int(segment["end"]):
            return segment
    return None


def _is_test_host(host_row: Optional[Dict[str, Any]]) -> bool:
    """判断主机是否属于测试网段；无法取得 IP 时不视为测试主机。"""
    if not host_row:
        return False
    for interface in host_row.get("interfaces") or []:
        raw_ip = str(interface.get("ip", "")).strip()
        if not raw_ip:
            continue
        try:
            address = ipaddress.ip_address(raw_ip)
        except ValueError:
            continue
        if any(address in network for network in get_test_host_networks()):
            return True
    return False


def _event_exclusion_reason(
    event_row: Dict[str, Any],
    hosts: Dict[str, Dict[str, Any]],
    triggers: Dict[str, Dict[str, Any]],
    analysis_clock: int,
    segments: Sequence[Dict[str, Any]],
    production_only: bool = False,
) -> Optional[str]:
    if production_only:
        triggerid = str(event_row.get("objectid", ""))
        trigger_row = triggers.get(triggerid) or {}
        hostid = _event_hostid(event_row) or _trigger_hostid(trigger_row)
        if hostid and _is_test_host(hosts.get(hostid)):
            return "test_network_excluded"

    if str(event_row.get("severity", "0")) == "0":
        return "unclassified"

    start_clock = _int(event_row.get("clock"), -1)
    if start_clock < 0 or start_clock > analysis_clock or _segment_for_clock(start_clock, segments) is None:
        return "timestamp_invalid"

    triggerid = str(event_row.get("objectid", ""))
    trigger_row = triggers.get(triggerid)
    if not triggerid or trigger_row is None:
        return "trigger_missing"

    hostid = _event_hostid(event_row) or _trigger_hostid(trigger_row)
    host_row = hosts.get(hostid)
    if not hostid or host_row is None:
        return "host_missing"
    return None


def _related_interface_abnormal(host_row: Dict[str, Any], trigger_row: Dict[str, Any]) -> bool:
    """判断直接采集型监控项实际使用的接口当前是否不可验证。"""
    interfaces = {
        str(interface.get("interfaceid", "")): interface
        for interface in (host_row.get("interfaces") or [])
        if interface.get("interfaceid")
    }
    for item in trigger_row.get("items") or []:
        item_type = str(item.get("type", ""))
        interfaceid = str(item.get("interfaceid", ""))
        # 只有被动 Agent、IPMI、JMX、SNMP 这类直接采集项才使用接口 available。
        # Simple check/ICMP、dependent、calculated 等即使带 interfaceid，也不能用
        # Agent 接口的 unknown 反推该监控项不可用。
        if item_type in {"0", "12", "16", "20"}:
            if not interfaceid or interfaceid == "0" or interfaceid not in interfaces:
                return True
            if str(interfaces[interfaceid].get("available", "0")) != "1":
                return True
        elif item_type == "7":
            if str(host_row.get("active_available", "0")) != "1":
                return True
    return False


def _monitoring_chain_unverifiable_reason(
    host_row: Dict[str, Any],
    trigger_row: Dict[str, Any],
) -> Optional[str]:
    """返回当前无法继续验证未恢复状态的首个监控链路原因。"""
    if str(host_row.get("status", "1")) != "0":
        return "host_disabled"
    if str(trigger_row.get("status", "1")) != "0":
        return "trigger_disabled"
    if str(trigger_row.get("state", "1")) != "0":
        return "trigger_unknown"
    items = trigger_row.get("items") or []
    if any(str(item.get("status", "1")) != "0" for item in items):
        return "item_disabled"
    if any(str(item.get("state", "0")) != "0" for item in items):
        return "item_not_supported"
    if _related_interface_abnormal(host_row, trigger_row):
        return "interface_abnormal"
    return None


def _current_status_notes(host_row: Dict[str, Any], trigger_row: Dict[str, Any]) -> List[str]:
    notes: List[str] = []
    if str(host_row.get("status", "1")) != "0":
        notes.append("主机当前停用")
    if str(trigger_row.get("status", "1")) != "0":
        notes.append("触发器当前禁用")
    if str(trigger_row.get("state", "1")) != "0":
        notes.append("触发器当前状态未知")
    if any(str(item.get("status", "1")) != "0" for item in (trigger_row.get("items") or [])):
        notes.append("关联监控项当前禁用")
    if any(str(item.get("state", "0")) != "0" for item in (trigger_row.get("items") or [])):
        notes.append("关联监控项当前不受支持")
    if _related_interface_abnormal(host_row, trigger_row):
        notes.append("相关监控接口当前不可用/未知")
    return notes


def _host_ip(host_row: Dict[str, Any]) -> str:
    interfaces = list(host_row.get("interfaces") or [])
    interfaces.sort(key=lambda item: (str(item.get("main", "0")) != "1", _int(item.get("type"), 99)))
    for interface in interfaces:
        if str(interface.get("useip", "1")) == "1" and interface.get("ip"):
            return str(interface["ip"])
        if interface.get("dns"):
            return str(interface["dns"])
    return "N/A"


def _current_state_start(
    acknowledges: Sequence[Dict[str, Any]],
    set_bit: int,
    unset_bit: int,
    current_enabled: bool,
    start_clock: int,
    analysis_clock: int,
) -> Optional[int]:
    if not current_enabled:
        return None
    current_start: Optional[int] = None
    ordered = sorted(acknowledges, key=lambda item: _int(item.get("clock"), -1))
    for update in ordered:
        clock = _int(update.get("clock"), -1)
        if not start_clock <= clock <= analysis_clock:
            continue
        action = _int(update.get("action"), 0)
        if action & unset_bit:
            current_start = None
        if action & set_bit:
            current_start = clock
    return current_start


def _is_manual_suppressed(event_row: Dict[str, Any]) -> bool:
    if str(event_row.get("suppressed", "0")) != "1":
        return False
    return any(
        str(item.get("maintenanceid", "")) == "0" and str(item.get("userid", "0")) not in ("", "0")
        for item in (event_row.get("suppression_data") or [])
    )


def _resolve_business_recovery(
    event_row: Dict[str, Any],
    recovery_events: Dict[str, Dict[str, Any]],
    start_clock: int,
    analysis_clock: int,
) -> Tuple[Optional[int], Optional[str], bool, bool]:
    candidates: List[Tuple[int, int, str]] = []
    priorities = {"actual": 0, "close": 1, "acknowledge": 2, "suppress": 3}

    r_eventid = str(event_row.get("r_eventid", "0"))
    recovery_row = recovery_events.get(r_eventid) if r_eventid != "0" else None
    if recovery_row and str(recovery_row.get("value", "")) == "0":
        clock = _int(recovery_row.get("clock"), -1)
        if start_clock <= clock <= analysis_clock:
            candidates.append((clock, priorities["actual"], "actual"))

    acknowledges = event_row.get("acknowledges") or []
    for update in acknowledges:
        clock = _int(update.get("clock"), -1)
        action = _int(update.get("action"), 0)
        if start_clock <= clock <= analysis_clock and action & 1:
            candidates.append((clock, priorities["close"], "close"))

    acknowledged_current = str(event_row.get("acknowledged", "0")) == "1"
    acknowledge_clock = _current_state_start(
        acknowledges, 2, 16, acknowledged_current, start_clock, analysis_clock
    )
    if acknowledge_clock is not None:
        candidates.append((acknowledge_clock, priorities["acknowledge"], "acknowledge"))

    manually_suppressed_current = _is_manual_suppressed(event_row)
    suppress_clock = _current_state_start(
        acknowledges, 32, 64, manually_suppressed_current, start_clock, analysis_clock
    )
    if suppress_clock is not None:
        candidates.append((suppress_clock, priorities["suppress"], "suppress"))

    if not candidates:
        return None, None, acknowledged_current, manually_suppressed_current
    clock, _, source = min(candidates)
    return clock, source, acknowledged_current, manually_suppressed_current


QUALITY_KEYS = [
    "raw_problem_events",
    "test_network_excluded",
    "unclassified",
    "host_missing",
    "host_disabled_included",
    "trigger_missing",
    "trigger_disabled_included",
    "trigger_unknown_included",
    "item_disabled_included",
    "item_unsupported_included",
    "interface_abnormal_included",
    "recovery_unverifiable",
    "current_monitoring_unverifiable",
    "recovery_before_problem",
    "timestamp_invalid",
    "valid_events",
]


def normalize_problem_events(
    events: Sequence[Dict[str, Any]],
    hosts: Dict[str, Dict[str, Any]],
    triggers: Dict[str, Dict[str, Any]],
    recovery_events: Dict[str, Dict[str, Any]],
    analysis_clock: int,
    segments: Sequence[Dict[str, Any]],
    production_only: bool = False,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """构建唯一事件底表；无效事件保留排除原因，但不会进入分析。"""
    quality = {key: 0 for key in QUALITY_KEYS}
    quality["raw_problem_events"] = len(events)
    records: List[Dict[str, Any]] = []

    for event_row in events:
        triggerid = str(event_row.get("objectid", ""))
        trigger_row = triggers.get(triggerid) or {}
        hostid = _event_hostid(event_row) or _trigger_hostid(trigger_row)
        start_clock = _int(event_row.get("clock"), -1)
        segment = _segment_for_clock(start_clock, segments) if start_clock >= 0 else None
        reason = _event_exclusion_reason(
            event_row, hosts, triggers, analysis_clock, segments, production_only,
        )
        event_hosts = event_row.get("hosts") or []
        fallback_name = event_hosts[0].get("name", "Unknown") if event_hosts else "Unknown"
        base = {
            "eventid": str(event_row.get("eventid", "")),
            "hostid": hostid,
            "host_name": ((hosts.get(hostid) or {}).get("name") or fallback_name),
            "host_ip": _host_ip(hosts[hostid]) if hostid in hosts else "N/A",
            "triggerid": triggerid,
            "problem_name": str(event_row.get("name") or trigger_row.get("description") or "Unknown"),
            "event_name": str(event_row.get("name", "Unknown")),
            "current_trigger_description": str(trigger_row.get("description", "")),
            "severity": str(event_row.get("severity", "0")),
            "start_clock": start_clock,
            "analysis_clock": analysis_clock,
            "host_status": str((hosts.get(hostid) or {}).get("status", "")),
            "trigger_status": str((triggers.get(triggerid) or {}).get("status", "")),
            "trigger_state": str((triggers.get(triggerid) or {}).get("state", "")),
            "current_status_notes": _current_status_notes(hosts[hostid], trigger_row) if hostid in hosts else [],
            "is_valid": reason is None,
            "exclude_reason": reason,
            "week_segment": segment["label"] if segment else None,
            "week_segment_key": segment["key"] if segment else None,
        }
        if reason is not None:
            quality[reason] += 1
            base.update({
                "recovery_clock": None,
                "is_recovered": False,
                "recovery_status_valid": False,
                "acknowledged_current": False,
                "manually_suppressed_current": False,
                "recovery_source": None,
                "duration_end_clock": None,
                "duration_seconds": None,
                "duration_valid": False,
                "duration_anomaly": None,
            })
            records.append(base)
            continue

        r_eventid = str(event_row.get("r_eventid", "0"))
        actual_recovery_anomaly: Optional[str] = None
        actual_recovery_clock: Optional[int] = None
        recovery_link_unverifiable = False
        if r_eventid != "0":
            recovery_row = recovery_events.get(r_eventid)
            if recovery_row is None or str(recovery_row.get("value", "")) != "0":
                recovery_link_unverifiable = True
            else:
                recovery_row_clock = _optional_int(recovery_row.get("clock"))
                if recovery_row_clock is None:
                    actual_recovery_anomaly = "recovery_timestamp_invalid"
                    quality["timestamp_invalid"] += 1
                elif recovery_row_clock > analysis_clock:
                    recovery_link_unverifiable = True
                elif recovery_row_clock < start_clock:
                    actual_recovery_anomaly = "recovery_before_problem"
                    actual_recovery_clock = recovery_row_clock
                    quality["recovery_before_problem"] += 1

        recovery_clock, recovery_source, acknowledged_current, manually_suppressed_current = _resolve_business_recovery(
            event_row, recovery_events, start_clock, analysis_clock
        )
        if actual_recovery_anomaly is not None:
            # r_eventid 已精确指向 value=0 的恢复事件，业务状态仍视为已恢复；
            # 但恢复时间不可用于计算时长，不能伪造成 0 秒或计算到脚本生成时间。
            recovery_clock = actual_recovery_clock
            recovery_source = "actual"
            is_recovered = True
            recovery_status_valid = True
            duration_end_clock = None
            duration_seconds = None
            duration_valid = False
            duration_anomaly = actual_recovery_anomaly
        elif recovery_clock is not None:
            is_recovered = True
            recovery_status_valid = True
            duration_end_clock = recovery_clock
            duration_seconds = max(0, duration_end_clock - start_clock)
            duration_valid = True
            duration_anomaly = None
        elif recovery_link_unverifiable:
            is_recovered = None
            recovery_status_valid = False
            duration_end_clock = None
            duration_seconds = None
            duration_valid = False
            duration_anomaly = "recovery_unverifiable"
            base["is_valid"] = False
            base["exclude_reason"] = "recovery_unverifiable"
            quality["recovery_unverifiable"] += 1
        elif _monitoring_chain_unverifiable_reason(hosts[hostid], trigger_row) is not None:
            is_recovered = None
            recovery_status_valid = False
            duration_end_clock = None
            duration_seconds = None
            duration_valid = False
            duration_anomaly = "current_monitoring_unverifiable"
            base["is_valid"] = False
            base["exclude_reason"] = "current_monitoring_unverifiable"
            quality["current_monitoring_unverifiable"] += 1
        else:
            is_recovered = recovery_clock is not None
            recovery_status_valid = True
            duration_end_clock = analysis_clock
            duration_seconds = max(0, duration_end_clock - start_clock)
            duration_valid = True
            duration_anomaly = None
        base.update({
            "recovery_clock": recovery_clock,
            "is_recovered": is_recovered,
            "recovery_status_valid": recovery_status_valid,
            "acknowledged_current": acknowledged_current,
            "manually_suppressed_current": manually_suppressed_current,
            "recovery_source": recovery_source,
            "duration_end_clock": duration_end_clock,
            "duration_seconds": duration_seconds,
            "duration_valid": duration_valid,
            "duration_anomaly": duration_anomaly,
        })
        if base["is_valid"]:
            if str((hosts.get(hostid) or {}).get("status", "1")) != "0":
                quality["host_disabled_included"] += 1
            if str(trigger_row.get("status", "1")) != "0":
                quality["trigger_disabled_included"] += 1
            if str(trigger_row.get("state", "1")) != "0":
                quality["trigger_unknown_included"] += 1
            items = trigger_row.get("items") or []
            if any(str(item.get("status", "1")) != "0" for item in items):
                quality["item_disabled_included"] += 1
            if any(str(item.get("state", "0")) != "0" for item in items):
                quality["item_unsupported_included"] += 1
            if _related_interface_abnormal(hosts[hostid], trigger_row):
                quality["interface_abnormal_included"] += 1
            quality["valid_events"] += 1
        records.append(base)

    return records, quality


def _ordered_segments(records: Sequence[Dict[str, Any]]) -> List[str]:
    ordered: List[str] = []
    for record in sorted(records, key=lambda row: (row["start_clock"], _stable_id(row["eventid"]))):
        label = record.get("week_segment")
        if label and label not in ordered:
            ordered.append(label)
    return ordered


def _group_records(records: Sequence[Dict[str, Any]]) -> Dict[Tuple[str, str], List[Dict[str, Any]]]:
    grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[(record["hostid"], record["triggerid"])].append(record)
    return grouped


def _problem_summary(group: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    first = group[0]
    return {
        "hostid": first["hostid"],
        "host": first["host_name"],
        "ip": first["host_ip"],
        "triggerid": first["triggerid"],
        "problem": first["problem_name"],
        "count": len(group),
        "week_segments": _ordered_segments(group),
        "current_status_notes": list(dict.fromkeys(
            note for row in group for note in (row.get("current_status_notes") or [])
        )),
    }


def _has_valid_duration(record: Dict[str, Any]) -> bool:
    """兼容旧测试记录，仅把明确可计算的持续时长交给时长类分析。"""
    return record.get("duration_seconds") is not None and record.get("duration_valid", True) is not False


def analyze_records(
    records: Sequence[Dict[str, Any]],
    segments: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """所有周度统计只读取统一事件底表。"""
    valid = [
        record for record in records
        if record.get("is_valid") and record.get("recovery_status_valid", True)
    ]
    recovered = [record for record in valid if record.get("is_recovered")]
    unrecovered = [record for record in valid if not record.get("is_recovered")]
    recovered_durations = [int(record["duration_seconds"]) for record in recovered if _has_valid_duration(record)]

    short_recovery_threshold = SHORT_RECOVERY_THRESHOLD_SECONDS
    chronic_p90 = calc_percentile(recovered_durations, CHRONIC_PERCENTILE) if recovered_durations else None
    if len(recovered_durations) >= ADAPTIVE_THRESHOLD_MIN_SAMPLES:
        chronic_threshold = max(CHRONIC_MIN_SECONDS, int(chronic_p90))
        chronic_source = "percentile"
    else:
        chronic_threshold = CHRONIC_FALLBACK_SECONDS
        chronic_source = "fallback"

    severity_count = {severity: 0 for severity in SEVERITY_ORDER}
    for record in valid:
        if record["severity"] in severity_count:
            severity_count[record["severity"]] += 1

    overview = {
        "total_events": len(valid),
        "unique_hosts": len({record["hostid"] for record in valid}),
        "unique_problems": len({(record["hostid"], record["triggerid"]) for record in valid}),
        "recovered_count": len(recovered),
        "unrecovered_count": len(unrecovered),
        "recovery_rate_denominator": len(valid),
        "recovery_rate": len(recovered) / len(valid) * 100 if valid else 0.0,
        "duration_valid_count": sum(1 for record in valid if _has_valid_duration(record)),
        "recovery_median": int(round(statistics.median(recovered_durations))) if recovered_durations else None,
        "recovery_p90": chronic_p90,
        "severity_count": severity_count,
    }

    time_slot_rows = []
    for slot_start in range(0, 24, 4):
        label = f"{slot_start:02d}-{slot_start + 4:02d}"
        count = sum(1 for record in valid if get_time_slot(record["start_clock"]) == label)
        time_slot_rows.append({
            "label": label,
            "count": count,
            "pct": count / len(valid) * 100 if valid else 0.0,
        })

    segment_rows: List[Dict[str, Any]] = []
    segment_definitions = list(segments or [])
    if not segment_definitions:
        for index, label in enumerate(_ordered_segments(valid), 1):
            segment_definitions.append({"key": f"S{index}", "label": label, "range": label, "is_full_week": False})

    previous_full_count: Optional[int] = None
    for segment in segment_definitions:
        segment_records = [
            record for record in valid
            if record.get("week_segment_key") == segment.get("key")
            or (not record.get("week_segment_key") and record.get("week_segment") == segment.get("label"))
        ]
        recovered_count = sum(1 for record in segment_records if record["is_recovered"])
        row = {
            "label": segment["label"],
            "range": segment["range"],
            "count": len(segment_records),
            "pct": len(segment_records) / len(valid) * 100 if valid else 0.0,
            "critical_count": sum(1 for record in segment_records if record["severity"] in ("4", "5")),
            "host_count": len({record["hostid"] for record in segment_records}),
            "problem_count": len({(record["hostid"], record["triggerid"]) for record in segment_records}),
            "recovery_rate": recovered_count / len(segment_records) * 100 if segment_records else 0.0,
            "change_pct": None,
            "is_full_week": bool(segment.get("is_full_week")),
        }
        if row["is_full_week"]:
            if previous_full_count is not None:
                row["change_pct"] = ((row["count"] - previous_full_count) / previous_full_count * 100) if previous_full_count else None
            previous_full_count = row["count"]
        segment_rows.append(row)

    host_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for record in valid:
        host_groups[record["hostid"]].append(record)
    high_frequency_hosts: List[Dict[str, Any]] = []
    for hostid, group in host_groups.items():
        problems_by_trigger: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for row in group:
            problems_by_trigger[row["triggerid"]].append(row)
        main_problems: List[Dict[str, Any]] = []
        for triggerid, problem_rows in problems_by_trigger.items():
            name_counts = Counter(row["problem_name"] for row in problem_rows)
            first_seen = {
                name: min(row["start_clock"] for row in problem_rows if row["problem_name"] == name)
                for name in name_counts
            }
            representative_name = min(name_counts, key=lambda name: (-name_counts[name], first_seen[name], name))
            main_problems.append({
                "triggerid": triggerid,
                "problem": representative_name,
                "count": len(problem_rows),
            })
        main_problems.sort(key=lambda row: (-row["count"], _stable_id(row["triggerid"])))
        first = group[0]
        high_frequency_hosts.append({
            "hostid": hostid,
            "host": first["host_name"],
            "ip": first["host_ip"],
            "count": len(group),
            "problem_count": len(problems_by_trigger),
            "week_segments": _ordered_segments(group),
            "current_status_notes": list(dict.fromkeys(
                note for row in group for note in (row.get("current_status_notes") or [])
            )),
            "main_problems": main_problems,
        })
    high_frequency_hosts.sort(key=lambda row: (-row["count"], -row["problem_count"], _stable_id(row["hostid"])))

    grouped = _group_records(valid)
    regular_problems: List[Dict[str, Any]] = []
    short_recovery_problems: List[Dict[str, Any]] = []
    chronic_problems: List[Dict[str, Any]] = []

    for group in grouped.values():
        summary = _problem_summary(group)
        slot_counts = Counter(get_time_slot(row["start_clock"]) for row in group)
        slot, slot_count = max(slot_counts.items(), key=lambda item: (item[1], item[0]))
        concentration = slot_count / len(group)
        if (
            len(group) >= REGULAR_MIN_EVENTS
            and len(summary["week_segments"]) >= REGULAR_MIN_SEGMENTS
            and concentration >= REGULAR_CONCENTRATION_RATIO
        ):
            slot_clocks = [row["start_clock"] for row in group if get_time_slot(row["start_clock"]) == slot]
            average_minutes = sum(
                datetime.fromtimestamp(clock, tz=BEIJING_TZ).hour * 60
                + datetime.fromtimestamp(clock, tz=BEIJING_TZ).minute
                for clock in slot_clocks
            ) / len(slot_clocks)
            regular_problems.append({
                **summary,
                "slot": slot,
                "concentration": concentration,
                "average_time": f"{int(average_minutes // 60):02d}:{int(average_minutes % 60):02d}",
            })

        recovered_group = [row for row in group if row["is_recovered"] and _has_valid_duration(row)]
        if len(recovered_group) >= SHORT_RECOVERY_MIN_RECOVERED_EVENTS:
            average_recovery = sum(row["duration_seconds"] for row in recovered_group) / len(recovered_group)
            if average_recovery <= short_recovery_threshold:
                short_recovery_problems.append({
                    **summary,
                    "recovered_count": len(recovered_group),
                    "avg_recovery": average_recovery,
                })

        chronic_events = [
            row for row in group
            if _has_valid_duration(row) and row["duration_seconds"] >= chronic_threshold
        ]
        if chronic_events:
            chronic_durations = [row["duration_seconds"] for row in chronic_events]
            chronic_problems.append({
                **summary,
                "chronic_count": len(chronic_events),
                "recovered_count": sum(1 for row in chronic_events if row["is_recovered"]),
                "unrecovered_count": sum(1 for row in chronic_events if not row["is_recovered"]),
                "max_duration": max(chronic_durations),
                "median_duration": int(round(statistics.median(chronic_durations))),
                "week_segments": _ordered_segments(chronic_events),
            })

    regular_problems.sort(key=lambda row: (-row["count"], -row["concentration"], _stable_id(row["hostid"]), _stable_id(row["triggerid"])))
    short_recovery_problems.sort(key=lambda row: (-row["count"], row["avg_recovery"], _stable_id(row["hostid"]), _stable_id(row["triggerid"])))
    chronic_problems.sort(key=lambda row: (-row["chronic_count"],-row["max_duration"], -row["count"], _stable_id(row["hostid"]), _stable_id(row["triggerid"])))

    critical: Dict[str, List[Dict[str, Any]]] = {"5": [], "4": []}
    for severity in ("5", "4"):
        severity_groups = _group_records([row for row in valid if row["severity"] == severity])
        for group in severity_groups.values():
            summary = _problem_summary(group)
            duration_values = [row["duration_seconds"] for row in group if _has_valid_duration(row)]
            critical[severity].append({
                **summary,
                "max_duration": max(duration_values) if duration_values else None,
                "recovered_count": sum(1 for row in group if row["is_recovered"]),
                "unrecovered_count": sum(1 for row in group if not row["is_recovered"]),
            })
        critical[severity].sort(key=lambda row: (
            -row["count"],
            -(row["max_duration"] if row["max_duration"] is not None else -1),
            _stable_id(row["hostid"]),
            _stable_id(row["triggerid"]),
        ))

    logger.info(
        "Weekly labels: regular=%s short_recovery=%s chronic=%s; duration_samples=%s",
        len(regular_problems),
        len(short_recovery_problems),
        len(chronic_problems),
        len(recovered_durations),
    )
    logger.info(
        "Weekly thresholds: short_recovery=%s (fixed); chronic=%s (source=%s, P90=%s, recovered_samples=%s)",
        format_duration(short_recovery_threshold),
        format_duration(chronic_threshold),
        chronic_source,
        format_optional_duration(chronic_p90),
        len(recovered_durations),
    )


    return {
        "overview": overview,
        "segments": segment_rows,
        "time_slots": time_slot_rows,
        "high_frequency_hosts": high_frequency_hosts,
        "regular_problems": regular_problems,
        "short_recovery_problems": short_recovery_problems,
        "chronic_problems": chronic_problems,
        "critical": critical,
        "thresholds": {
            "duration_sample_count": len(recovered_durations),
            "short_recovery_threshold": short_recovery_threshold,
            "chronic_p90": chronic_p90,
            "chronic_threshold": chronic_threshold,
            "chronic_source": chronic_source,
        },
    }


def build_analysis_diagnostics(
    records: Sequence[Dict[str, Any]],
    analysis: Dict[str, Any],
) -> Dict[str, Any]:
    """生成阈值和展示数量诊断数据，不参与正式报表统计。"""
    valid = [
        record for record in records
        if record.get("is_valid") and record.get("recovery_status_valid", True)
    ]
    grouped = _group_records(valid)
    recovered_durations = [
        int(record["duration_seconds"])
        for record in valid
        if record.get("is_recovered") and _has_valid_duration(record)
    ]

    duration_percentiles = {
        int(percentile * 100): calc_percentile(recovered_durations, percentile)
        for percentile in DIAGNOSTIC_DURATION_PERCENTILES
    } if recovered_durations else {}

    chronic_candidates: Dict[int, Dict[str, int]] = {}
    for threshold in DIAGNOSTIC_CHRONIC_THRESHOLDS:
        matching = [
            record for record in valid
            if _has_valid_duration(record) and int(record["duration_seconds"]) >= threshold
        ]
        chronic_candidates[threshold] = {
            "events": len(matching),
            "problems": len({(record["hostid"], record["triggerid"]) for record in matching}),
        }

    short_candidates: Dict[int, Dict[str, int]] = {}
    for threshold in DIAGNOSTIC_SHORT_THRESHOLDS:
        matching_groups = []
        for group in grouped.values():
            recovered_group = [
                record for record in group
                if record.get("is_recovered") and _has_valid_duration(record)
            ]
            if len(recovered_group) < SHORT_RECOVERY_MIN_RECOVERED_EVENTS:
                continue
            average = sum(int(record["duration_seconds"]) for record in recovered_group) / len(recovered_group)
            if average <= threshold:
                matching_groups.append(group)
        short_candidates[threshold] = {
            "events": sum(len(group) for group in matching_groups),
            "problems": len(matching_groups),
        }

    regular_candidates: Dict[float, Dict[str, int]] = {}
    for ratio in DIAGNOSTIC_REGULAR_RATIOS:
        matching_groups = []
        for group in grouped.values():
            if len(group) < REGULAR_MIN_EVENTS or len(_ordered_segments(group)) < REGULAR_MIN_SEGMENTS:
                continue
            slot_count = max(Counter(get_time_slot(row["start_clock"]) for row in group).values())
            if slot_count / len(group) >= ratio:
                matching_groups.append(group)
        regular_candidates[ratio] = {
            "events": sum(len(group) for group in matching_groups),
            "problems": len(matching_groups),
        }

    coverage_sources = {
        "high_frequency": (analysis["high_frequency_hosts"], "count"),
        "regular": (analysis["regular_problems"], "count"),
        "short_recovery": (analysis["short_recovery_problems"], "count"),
        "chronic": (analysis["chronic_problems"], "chronic_count"),
        "disaster": (analysis["critical"]["5"], "count"),
        "severe": (analysis["critical"]["4"], "count"),
    }
    top_coverage = {
        name: {
            limit: _detail_coverage(rows, rows[:limit], count_key)
            for limit in DIAGNOSTIC_TOP_LIMITS
        }
        for name, (rows, count_key) in coverage_sources.items()
    }

    return {
        "duration_sample_count": len(recovered_durations),
        "duration_percentiles": duration_percentiles,
        "chronic_candidates": chronic_candidates,
        "short_candidates": short_candidates,
        "regular_candidates": regular_candidates,
        "top_coverage": top_coverage,
    }


def _format_candidate_counts(values: Dict[Any, Dict[str, int]], label) -> str:
    return " ".join(
        f"{label(key)}={counts['events']}次/{counts['problems']}项"
        for key, counts in values.items()
    )


def _format_top_coverage(values: Dict[int, float]) -> str:
    return " ".join(f"Top{limit}={coverage:.1f}%" for limit, coverage in values.items())


def log_weekly_diagnostics(
    records: Sequence[Dict[str, Any]],
    analysis: Dict[str, Any],
    quality: Dict[str, int],
) -> Dict[str, Any]:
    """把后续调参所需数据写入正常 INFO 日志。"""
    diagnostics = build_analysis_diagnostics(records, analysis)
    overview = analysis["overview"]
    duration_valid_count = overview["duration_valid_count"]
    duration_coverage = duration_valid_count / quality["valid_events"] * 100 if quality["valid_events"] else 0.0
    logger.info(
        "Weekly event quality: raw=%s valid=%s excluded_unverifiable=%s recovered=%s unrecovered=%s "
        "duration_valid=%s duration_coverage=%.1f%%",
        quality["raw_problem_events"],
        quality["valid_events"],
        quality["recovery_unverifiable"] + quality["current_monitoring_unverifiable"],
        overview["recovered_count"],
        overview["unrecovered_count"],
        duration_valid_count,
        duration_coverage,
    )
    percentiles = diagnostics["duration_percentiles"]
    if percentiles:
        logger.info(
            "Weekly duration percentiles (recovered valid samples=%s): %s",
            diagnostics["duration_sample_count"],
            " ".join(f"P{percentile}={format_duration(value)}" for percentile, value in percentiles.items()),
        )
    else:
        logger.info("Weekly duration percentiles: no valid recovered duration samples")

    logger.info(
        "Weekly chronic candidates: %s",
        _format_candidate_counts(
            diagnostics["chronic_candidates"],
            lambda seconds: f">={format_duration(seconds)}",
        ),
    )
    logger.info(
        "Weekly short-recovery candidates (min %s recovered events, group average): %s",
        SHORT_RECOVERY_MIN_RECOVERED_EVENTS,
        _format_candidate_counts(
            diagnostics["short_candidates"],
            lambda seconds: f"<={format_duration(seconds)}",
        ),
    )
    logger.info(
        "Weekly regular candidates (min %s events/%s days): %s",
        REGULAR_MIN_EVENTS,
        REGULAR_MIN_SEGMENTS,
        _format_candidate_counts(
            diagnostics["regular_candidates"],
            lambda ratio: f">={ratio:.0%}",
        ),
    )

    coverage_names = {
        "high_frequency": "high_frequency_hosts",
        "regular": "regular",
        "short_recovery": "short_recovery",
        "chronic": "chronic",
        "disaster": "disaster",
        "severe": "severe",
    }
    logger.info(
        "Weekly Top coverage: %s",
        " | ".join(
            f"{coverage_names[name]}[{_format_top_coverage(values)}]"
            for name, values in diagnostics["top_coverage"].items()
        ),
    )
    logger.info(
        "Weekly exclusions: test_network_excluded=%s unclassified=%s host_missing=%s trigger_missing=%s "
        "recovery_unverifiable=%s current_monitoring_unverifiable=%s timestamp_invalid=%s",
        quality["test_network_excluded"],
        quality["unclassified"],
        quality["host_missing"],
        quality["trigger_missing"],
        quality["recovery_unverifiable"],
        quality["current_monitoring_unverifiable"],
        quality["timestamp_invalid"],
    )
    logger.info(
        "Weekly retained annotations: host_disabled=%s trigger_disabled=%s trigger_unknown=%s "
        "item_disabled=%s item_unsupported=%s interface_abnormal=%s recovery_before_problem=%s",
        quality["host_disabled_included"],
        quality["trigger_disabled_included"],
        quality["trigger_unknown_included"],
        quality["item_disabled_included"],
        quality["item_unsupported_included"],
        quality["interface_abnormal_included"],
        quality["recovery_before_problem"],
    )
    return diagnostics


def apply_top_limit(items: Sequence[Any], limit: int) -> List[Any]:
    if limit < -1:
        raise ValueError("Top N parameter must be -1 or a non-negative integer")
    if limit == -1:
        return list(items)
    if limit == 0:
        return []
    return list(items[:limit])


def default_top_limits() -> Dict[str, int]:
    return {
        "high_frequency": TOP_N_HIGH_FREQUENCY_HOSTS,
        "regular": TOP_N_REGULAR_PROBLEMS,
        "short_recovery": TOP_N_SHORT_RECOVERY_PROBLEMS,
        "chronic": TOP_N_CHRONIC_PROBLEMS,
        "disaster": TOP_N_DISASTER_EVENTS,
        "severe": TOP_N_SEVERE_EVENTS,
    }


def merged_top_limits(overrides: Optional[Dict[str, int]] = None) -> Dict[str, int]:
    """把调用方的章节覆盖项合并到模块默认值上，None 覆盖项忽略。"""
    limits = default_top_limits()
    unknown = set(overrides or {}) - set(limits)
    if unknown:
        raise ValueError(f"Unknown Top N parameters: {', '.join(sorted(unknown))}")
    for name, value in (overrides or {}).items():
        if value is not None:
            limits[name] = value
    _validate_top_limits(limits)
    return limits


def _validate_top_limits(limits: Dict[str, int]) -> None:
    expected = {"high_frequency", "regular", "short_recovery", "chronic", "disaster", "severe"}
    missing = expected - limits.keys()
    if missing:
        raise ValueError(f"Missing Top N parameters: {', '.join(sorted(missing))}")
    for name in expected:
        value = limits[name]
        if not isinstance(value, int) or value < -1:
            raise ValueError(f"Invalid Top N parameter {name}={value!r}")


def _display_description(limit: int, unit: str) -> str:
    return "全部展示" if limit == -1 else f"展示前 {limit} {unit}"


def _current_status_suffix(row: Dict[str, Any]) -> str:
    notes = row.get("current_status_notes") or []
    return f" ⚠️ {'、'.join(notes)}" if notes else ""


def _detail_coverage(rows: Sequence[Dict[str, Any]], visible: Sequence[Dict[str, Any]], count_key: str) -> float:
    total = sum(int(row.get(count_key, 0)) for row in rows)
    shown = sum(int(row.get(count_key, 0)) for row in visible)
    return shown / total * 100 if total else 0.0


def _detail_count(rows: Sequence[Dict[str, Any]], count_key: str) -> int:
    return sum(int(row.get(count_key, 0)) for row in rows)


def _chapter_number(number: int) -> str:
    values = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七", 8: "八", 9: "九"}
    return values.get(number, str(number))


def empty_report_data(
    start_str: str,
    end_str: str,
    time_from: int,
    time_till: int,
    analysis_clock: int,
) -> Dict[str, Any]:
    return {
        "meta": {
            "start_str": start_str,
            "end_str": end_str,
            "time_from": time_from,
            "time_till": time_till,
            "analysis_clock": analysis_clock,
        },
        "analysis": analyze_records([]),
        "quality": {key: 0 for key in QUALITY_KEYS},
    }


def render_weekly_report(data: Dict[str, Any], top_limits: Optional[Dict[str, int]] = None) -> str:
    """渲染保存与推送共同使用的完整 Markdown 周报。"""
    limits = dict(top_limits or default_top_limits())
    _validate_top_limits(limits)
    meta = data["meta"]
    analysis = data["analysis"]
    overview = analysis["overview"]
    lines: List[str] = []

    lines.append(f"## 📊 运维周报（{meta['start_str']} - {meta['end_str']}）")
    lines.append("")
    lines.append(f"> 统计范围：{meta['start_str']} 00:00:00 - {meta['end_str']} 23:59:59  ")
    lines.append(f"> 生成时间：{datetime.fromtimestamp(meta['analysis_clock'], tz=BEIJING_TZ).strftime('%Y-%m-%d %H:%M:%S')}  ")
    lines.append("> 统计范围：不含未分类级别；排除无法归属的主机、已删除触发器及无法核验的事件；当前状态异常仅在已有明确恢复依据时保留并标注  ")
    if meta.get("production_only"):
        excluded = data["quality"].get("test_network_excluded", 0)
        networks = get_test_host_networks()
        if networks:
            cidrs = "、".join(str(net) for net in networks)
            lines.append(f"> 生产口径：已排除测试网段（{cidrs}）主机的 {excluded} 条事件  ")
        else:
            lines.append(f"> 生产口径：未配置 {TEST_NETWORKS_ENV_VAR}，未执行测试网段排除  ")
    lines.append("> 恢复依据：问题恢复、人工确认、关闭或抑制问题")
    lines.extend(["", "---", "", "## 一、周度概览", ""])
    lines.append(f"🔔 报警次数：{overview['total_events']:,} 次  ")
    lines.append(f"🖥️ 报警主机：{overview['unique_hosts']} 台  ")
    lines.append(f"📋 问题类型：{overview['unique_problems']} 个  ")
    lines.append(f"✅ 已恢复：{overview['recovered_count']} 次（{overview['recovery_rate']:.2f}%）  ")
    lines.append(f"⚠️ 未恢复：{overview['unrecovered_count']} 次  ")
    if overview["recovery_median"] is None or overview["recovery_p90"] is None:
        lines.append("⏱️ 恢复时长：统计量不足")
    else:
        lines.append(f"⏱️ 恢复时长：P50 {format_duration(overview['recovery_median'])} / P90 {format_duration(overview['recovery_p90'])}  ")
    duration_coverage = overview["duration_valid_count"] / overview["total_events"] * 100 if overview["total_events"] else 0.0
    lines.append(f"🧪 统计量：{overview['duration_valid_count']}/{overview['total_events']}（{duration_coverage:.1f}%）")
    lines.extend(["", "### 严重级别分布", ""])
    for severity in SEVERITY_ORDER:
        count = overview["severity_count"][severity]
        pct = count / overview["total_events"] * 100 if overview["total_events"] else 0.0
        lines.append(f"{SEVERITY_EMOJIS[severity]} {SEVERITY_NAMES[severity]}：{count} 次（{pct:.1f}%）  ")

    lines.extend(["", "---", "", "## 二、每日趋势", ""])
    for row in analysis["segments"]:
        lines.append(f"**{row['label']}（{row['range']}）**")
        lines.append("")
        lines.append(f"> 报警：{row['count']} 次（{row['pct']:.1f}%）  ")
        lines.append(f"> 严重/灾难：{row['critical_count']} 次  ")
        lines.append(f"> 主机：{row['host_count']} 台 | 问题类型：{row['problem_count']} 个  ")
        lines.append(f"> 恢复率：{row['recovery_rate']:.1f}%  ")
        lines.append("")
    if analysis["segments"]:
        peak_day = max(analysis["segments"], key=lambda row: row["count"])
        workday_count = sum(row["count"] for row in analysis["segments"][:5])
        weekend_count = sum(row["count"] for row in analysis["segments"][5:])
        lines.append(f"📍 报警最高日：{peak_day['label']}（{peak_day['range']}，{peak_day['count']} 次）  ")
        lines.append(f"工作日：{workday_count} 次 | 周末：{weekend_count} 次")
    else:
        lines.append("✅ 本周无报警")

    lines.extend(["", "---", "", "## 三、时段分析", ""])
    for row in analysis["time_slots"]:
        lines.append(f"**{row['label']}**：{row['count']} 次（{row['pct']:.1f}%）  ")
    peak_slot = max(analysis["time_slots"], key=lambda row: row["count"])
    lines.extend(["", f"📍 报警最高时段：{peak_slot['label']}（{peak_slot['count']} 次）"])

    chapter = 4
    if limits["high_frequency"] != 0:
        rows = analysis["high_frequency_hosts"]
        visible = apply_top_limit(rows, limits["high_frequency"])
        lines.extend(["", "---", "", f"## {_chapter_number(chapter)}、高频报警主机", ""])
        chapter += 1
        lines.append(
            f"> 总览：涉及 {len(rows)} 台主机、累计 {_detail_count(rows, 'count')} 次报警；"
            f"{_display_description(limits['high_frequency'], '台')}共 {_detail_count(visible, 'count')} 次，"
            f"覆盖本周有效报警的 {_detail_coverage(rows, visible, 'count'):.1f}%  "
        )
        lines.append("")
        if visible:
            for index, row in enumerate(visible, 1):
                lines.append(f"**{index}. {row['host']}（{row['ip']}）**{_current_status_suffix(row)}  ")
                lines.append("")
                lines.append(f"> 出现日期：{'、'.join(row['week_segments']) or '-'}  ")
                lines.append(f"> 本周报警：{row['count']} 次  ")
                lines.append(f"> 问题类型：{row['problem_count']} 个  ")
                lines.append("> 主要问题：  ")
                for problem in row["main_problems"]:
                    pct = problem["count"] / row["count"] * 100
                    lines.append(f"> - {problem['problem']}：{problem['count']} 次（{pct:.1f}%）  ")
                lines.append("")
        else:
            lines.append("✅ 本周无高频报警主机")

    if limits["regular"] != 0:
        rows = analysis["regular_problems"]
        visible = apply_top_limit(rows, limits["regular"])
        lines.extend(["", "---", "", f"## {_chapter_number(chapter)}、规律型问题", ""])
        chapter += 1
        lines.append(
            f"> 总览：共 {len(rows)} 个主机问题组合、累计 {_detail_count(rows, 'count')} 次报警；"
            f"{_display_description(limits['regular'], '个')}共 {_detail_count(visible, 'count')} 次，"
            f"覆盖本类报警的 {_detail_coverage(rows, visible, 'count'):.1f}%  "
        )
        lines.append("")
        if visible:
            for index, row in enumerate(visible, 1):
                lines.append(f"**{index}. {row['host']}（{row['ip']}）**{_current_status_suffix(row)}  ")
                lines.append("")
                lines.append(f"> 问题：{row['problem']}  ")
                lines.append(f"> 出现日期：{'、'.join(row['week_segments'])}  ")
                lines.append(f"> 本周报警：{row['count']} 次  ")
                lines.append(f"> 规律时段：{row['slot']}（占该问题 {row['concentration'] * 100:.1f}%）  ")
                lines.append(f"> 时段内平均发生时间：{row['average_time']}")
                lines.append("")
        else:
            lines.append("✅ 本周无满足条件的规律型问题")

    if limits["short_recovery"] != 0:
        rows = analysis["short_recovery_problems"]
        visible = apply_top_limit(rows, limits["short_recovery"])
        lines.extend(["", "---", "", f"## {_chapter_number(chapter)}、短时恢复型问题", ""])
        chapter += 1
        lines.append(
            f"> 总览：共 {len(rows)} 个主机问题组合、累计 {_detail_count(rows, 'count')} 次报警；"
            f"{_display_description(limits['short_recovery'], '个')}共 {_detail_count(visible, 'count')} 次，"
            f"覆盖本类报警的 {_detail_coverage(rows, visible, 'count'):.1f}%  "
        )
        lines.append(f"> 阈值：{format_duration(SHORT_RECOVERY_THRESHOLD_SECONDS)}  ")
        lines.append("")
        if visible:
            for index, row in enumerate(visible, 1):
                lines.append(f"**{index}. {row['host']}（{row['ip']}）**{_current_status_suffix(row)}  ")
                lines.append("")
                lines.append(f"> 问题：{row['problem']}  ")
                lines.append(f"> 出现日期：{'、'.join(row['week_segments'])}  ")
                lines.append(f"> 本周报警：{row['count']} 次 | 有效恢复样本：{row['recovered_count']} 次  ")
                lines.append(f"> 平均恢复：{format_duration(row['avg_recovery'])}")
                lines.append("")
        else:
            lines.append("✅ 本周无满足条件的短时恢复型问题")

    if limits["chronic"] != 0:
        rows = analysis["chronic_problems"]
        visible = apply_top_limit(rows, limits["chronic"])
        threshold = analysis["thresholds"]["chronic_threshold"]
        lines.extend(["", "---", "", f"## {_chapter_number(chapter)}、持续型问题", ""])
        chapter += 1
        lines.append(
            f"> 总览：共 {len(rows)} 个主机问题组合、累计 {_detail_count(rows, 'chronic_count')} 次持续型报警；"
            f"{_display_description(limits['chronic'], '个')}共 {_detail_count(visible, 'chronic_count')} 次，"
            f"覆盖本类报警的 {_detail_coverage(rows, visible, 'chronic_count'):.1f}%  "
        )
        lines.append(f"> 阈值：单次问题持续时间 ≥ {format_duration(threshold)}")
        lines.append("")
        if visible:
            for index, row in enumerate(visible, 1):
                lines.append(f"**{index}. {row['host']}（{row['ip']}）**{_current_status_suffix(row)}  ")
                lines.append("")
                lines.append(f"> 问题：{row['problem']}  ")
                lines.append(f"> 出现日期：{'、'.join(row['week_segments'])}  ")
                lines.append(f"> 达到持续阈值：{row['chronic_count']} 次 / 该问题本周报警：{row['count']} 次  ")
                lines.append(f"> 持续型状态：已恢复 {row['recovered_count']} 次 | 未恢复 {row['unrecovered_count']} 次  ")
                lines.append(f"> 最长持续：{format_duration(row['max_duration'])} | P50：{format_duration(row['median_duration'])}")
                lines.append("")
        else:
            lines.append("✅ 本周无满足条件的持续型问题")

    if limits["disaster"] != 0 or limits["severe"] != 0:
        enabled = [
            item for item in [("5", "disaster", "灾难"), ("4", "severe", "严重")]
            if limits[item[1]] != 0
        ]
        lines.extend(["", "---", "", f"## {_chapter_number(chapter)}、严重事件", ""])
        summary_parts = []
        enabled_records: List[Dict[str, Any]] = []
        for severity, key, name in enabled:
            rows = analysis["critical"][severity]
            enabled_records.extend(rows)
            summary_parts.append(f"{name} {len(rows)} 个主机问题（{sum(row['count'] for row in rows)} 次）")
        lines.append(f"> 总览：{'，'.join(summary_parts)}  ")
        lines.append(f"> 主机：{len({row['hostid'] for row in enabled_records})} 台  ")
        for severity, key, name in enabled:
            rows = analysis["critical"][severity]
            visible = apply_top_limit(rows, limits[key])
            lines.extend(["", f"### {name}", ""])
            lines.append(
                f"> {_display_description(limits[key], '个')}共 {_detail_count(visible, 'count')} 次，"
                f"覆盖本级别报警的 {_detail_coverage(rows, visible, 'count'):.1f}%"
            )
            lines.append("")
            if visible:
                for index, row in enumerate(visible, 1):
                    lines.append(f"**{index}. {row['host']}（{row['ip']}）**{_current_status_suffix(row)}  ")
                    lines.append("")
                    lines.append(f"> 问题：{row['problem']}  ")
                    lines.append(f"> 报警：{row['count']} 次 | 出现日期：{'、'.join(row['week_segments'])}  ")
                    lines.append(f"> 状态：已恢复 {row['recovered_count']} 次 | 未恢复 {row['unrecovered_count']} 次  ")
                    lines.append(f"> 最长持续：{format_optional_duration(row['max_duration'])}")
                    lines.append("")
            else:
                lines.append(f"✅ 本周无{name}级别事件")

    lines.extend(["", "---", ""])
    return "\n".join(lines)


def generate_weekly_report(
    client: ZabbixCallClient,
    date: str = "last_week",
    analysis_clock: Optional[int] = None,
    production_only: bool = False,
    top_limits: Optional[Dict[str, int]] = None,
) -> str:
    analysis_clock = analysis_clock or int(datetime.now(BEIJING_TZ).timestamp())
    time_from, time_till, start_str, end_str, segments = get_week_range(date)
    logger.info("Generating weekly report for %s - %s", start_str, end_str)

    candidates = fetch_problem_events(client, time_from, time_till)
    triggerids = [str(row.get("objectid", "")) for row in candidates]
    triggers = fetch_current_triggers(client, triggerids)
    hostids = [
        _event_hostid(row) or _trigger_hostid(triggers.get(str(row.get("objectid", ""))) or {})
        for row in candidates
    ]
    hosts = fetch_current_hosts(client, hostids)

    valid_candidates = [
        row for row in candidates
        if _event_exclusion_reason(row, hosts, triggers, analysis_clock, segments, production_only) is None
    ]
    recovery_ids = [str(row.get("r_eventid", "0")) for row in valid_candidates]
    recovery_events = fetch_recovery_events(client, recovery_ids)

    records, quality = normalize_problem_events(
        candidates, hosts, triggers, recovery_events, analysis_clock, segments, production_only,
    )
    analysis = analyze_records(records, segments)
    report_data = {
        "meta": {
            "start_str": start_str,
            "end_str": end_str,
            "time_from": time_from,
            "time_till": time_till,
            "analysis_clock": analysis_clock,
            "production_only": production_only,
        },
        "analysis": analysis,
        "quality": quality,
    }
    log_weekly_diagnostics(records, analysis, quality)
    report = render_weekly_report(report_data, merged_top_limits(top_limits))
    return report
