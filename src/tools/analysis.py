"""Analysis Tools - MCP tools for data analysis and summaries."""
import json
import logging
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Annotated, Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field

# 北京时区常量
BEIJING_TZ = timezone(timedelta(hours=8))

# ===== 已拆分域模块的转发（兼容既有导入，见各域模块实现） =====
from .trend import trend_get, trend_summary  # noqa: F401
from .trend import (  # noqa: F401
    TrendStats,
    TrendChange,
    TrendVolatility,
    TrendCoverage,
    TrendSummaryResult,
    TrendSummaryErrorResponse,
)
from ._analysis_common import PROBLEM_VIEW_LABELS, PROBLEM_REASON_LABELS  # noqa: F401
from .problem import get_problem_summary, get_problem_fact_detail  # noqa: F401
from .problem import _parse_problem_time_range  # 暂借 problem 域辅助，health 拆分时归位

from client import get_zabbix_client
from config import (
    BEFORE_WINDOW_HOURS,
    DEFAULT_QUERY_DAYS,
)
from utils.params import parse_int_param, parse_list_param, parse_dict_param, parse_time_param
from utils.format import format_response, format_table, format_duration
from services.event_paginator import fetch_all_eventid_pages
from services.problem_status import (
    AttentionStatus,
    DispositionStatus,
    IncompleteProblemDataError,
    IndeterminateReason,
    LifecycleStatus,
    ProblemFact,
    ProblemStatusResult,
    ZabbixUpdateAction,
    analyze_current_problems,
    analyze_problem_event,
    analyze_problem_events,
)

logger = logging.getLogger(__name__)

QUICK_STATUS_PAGE_SIZE = 1000

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


def _resolve_health_host(client: Any, identifier: str) -> Optional[Dict[str, Any]]:
    """按明确路由解析主机，不把 API 失败伪装成未找到。"""
    output = ["hostid", "host", "name", "status", "active_available"]
    normalized = identifier.strip()
    if normalized.isdigit():
        rows = client.host.get(hostids=[normalized], output=output)
        return rows[0] if rows else None

    if re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", normalized):
        interfaces = client.hostinterface.get(
            filter={"ip": normalized},
            output=["hostid"],
        )
        if not interfaces:
            return None
        rows = client.host.get(
            hostids=[str(interfaces[0].get("hostid", ""))],
            output=output,
        )
        return rows[0] if rows else None

    rows = client.host.get(
        filter={"name": normalized},
        output=output,
        limit=1,
    )
    if rows:
        return rows[0]
    rows = client.host.get(
        search={"name": normalized},
        searchWildcardsEnabled=False,
        output=output,
        limit=1,
    )
    return rows[0] if rows else None


def _health_range_label(time_range: str) -> str:
    normalized = str(time_range).strip().lower()
    if normalized.isdigit():
        return f"开始时间不早于 Unix 时间戳 {normalized} 的当前问题"
    return f"最近 {normalized} 内开始的当前问题"


def _interface_availability(
    host_status: str,
    interfaces: List[Dict[str, Any]],
    used_interfaceids: set[str],
) -> str:
    if host_status != "0":
        return "停用"
    used_interfaces = [
        interface for interface in interfaces
        if str(interface.get("interfaceid", "")) in used_interfaceids
    ]
    values = {str(interface.get("available", "0")) for interface in used_interfaces}
    if "1" in values:
        return "在线"
    if "2" in values:
        return "离线"
    return "未知"


def check_host_health(
    host_identifier: Annotated[str, Field(description="主机标识（IP/主机名/hostid）")],
    time_range: Annotated[str, Field(description="告警时间范围（默认24h）")] = "24h",
    include_trends: Annotated[bool, Field(description="是否包含趋势数据")] = False,
    trend_hours: Annotated[int, Field(description="趋势数据查询时长")] = 24,
    include_oracle: Annotated[bool, Field(description="是否查询Oracle相关指标")] = False
) -> str:
    """按主机查询接口可用性、统一当前问题分类和关键指标。"""
    client = get_zabbix_client()
    now = int(time.time())
    try:
        time_from = _parse_problem_time_range(time_range, now)
    except ValueError as exc:
        return f"检查主机健康失败: {exc}"

    try:
        host_info = _resolve_health_host(client, host_identifier)
    except Exception as exc:
        return f"主机识别失败: {exc}"
    if host_info is None:
        return f"未找到主机: {host_identifier}"

    hostid = str(host_info.get("hostid", ""))
    host_name = str(host_info.get("name") or host_info.get("host") or host_identifier)
    try:
        items = client.item.get(
            hostids=[hostid],
            output=[
                "itemid", "name", "key_", "lastvalue", "units", "lastclock",
                "interfaceid", "status", "state", "type",
            ],
        )
    except Exception as exc:
        return f"获取主机接口关联失败: {exc}"
    used_interfaceids = {
        str(item.get("interfaceid"))
        for item in items
        if str(item.get("status", "1")) == "0"
        and str(item.get("interfaceid", "0")) not in {"", "0"}
    }
    try:
        interfaces = client.hostinterface.get(
            hostids=[hostid],
            output=["interfaceid", "hostid", "main", "type", "useip", "ip", "dns", "available", "error"],
        )
    except Exception as exc:
        return f"获取主机接口状态失败: {exc}"

    availability = _interface_availability(
        str(host_info.get("status", "1")),
        interfaces,
        used_interfaceids,
    )
    try:
        problem_summary = analyze_current_problems(
            client,
            analysis_clock=now,
            hostids=[hostid],
            time_from=time_from,
        )
    except Exception as exc:
        return f"获取主机当前问题失败: {exc}"

    actionable = problem_summary.by_status(AttentionStatus.ACTIONABLE)
    handled = problem_summary.by_status(AttentionStatus.HANDLED_ACTIVE)
    host_status_label = "启用" if str(host_info.get("status", "1")) == "0" else "停用"

    result = f"## 主机健康: {host_name}\n\n"
    result += f"- HostID: {hostid}\n"
    result += f"- 主机状态: {host_status_label}\n"
    result += f"- 接口可用性: {availability}\n"
    result += f"- 查询范围: {_health_range_label(time_range)}\n\n"
    result += "### 当前问题分类\n"
    result += f"- Zabbix 原始当前问题: {problem_summary.raw_count}\n"
    result += f"- 当前需处理: {len(actionable)}\n"
    result += f"- 已处置但仍在触发: {len(handled)}\n\n"

    severity_icons = {"5": "🚨", "4": "🔴", "3": "🟠", "2": "🟡", "1": "🔵", "0": "⚪"}
    if actionable:
        result += "#### 当前需处理\n"
        for fact in actionable[:10]:
            result += f"- {severity_icons.get(fact.severity, '⚪')} {fact.name}（事件 {fact.eventid}）\n"
        result += "\n"
    if handled:
        result += "#### 已处置但仍在触发\n"
        for fact in handled[:10]:
            result += f"- {severity_icons.get(fact.severity, '⚪')} {fact.name}（事件 {fact.eventid}，实际未恢复）\n"
        result += "\n"
    if not actionable and not handled:
        result += "当前没有可验证的在触发问题。\n\n"

    # 4. 获取关键指标
    try:
        # 智能评分算法（基于实际API查询结果）
        category_rules = {
            "cpu": {
                "keywords": [
                    # Linux 标准
                    "system.cpu.util",
                    # Windows perf_counter
                    "perf_counter[\\processor", "perf_counter_en[\\processor",
                    "processor information(_total)",
                    # 华为服务器 iBMC
                    "systemCpuUsage",
                    # 华为存储 OceanStor
                    "huawei.oceanstor.v6.controller.cpu",
                    "huawei.5300.v5[hwInfoControllerCPUUsage",
                    "huawei-server.systemCpuUsage",
                    # Dell 服务器
                    "dell.server.system.get",
                    "dell.server.hw.diskarray",
                    # 华鲲/浪潮等国产服务器
                    "cpuAvailability", "cpuStatus[", "cpuCoreCount",
                    # 通用硬件监控
                    "hardware.cpu.usage",
                    "ipmi.sensor", "snmp.cpu"
                ],
                "score": 100
            },
            "memory": {
                "keywords": [
                    # Linux 标准 - 使用率（已使用百分比）
                    "vm.memory.size[pused]",
                    "vm.memory.utilization", "vm.memory.util",
                    # Linux 备选（原始值，降权）
                    "vm.memory.size[used]",
                    # Windows perf_counter
                    "perf_counter[\\memory", "perf_counter_en[\\memory",
                    # 华为服务器 iBMC
                    "systemMemUsage",
                    # 华为存储 OceanStor
                    "huawei.oceanstor.v6.controller.memory",
                    "huawei.5300.v5[hwInfoControllerMemoryUsage",
                    "huawei-server.systemMemUsage",
                    # 通用物理机
                    "memoryStatus[", "memoryEntireStatus",
                    "hardware.memory.usage",
                    "ipmi.sensor", "snmp.memory"
                ],
                "score": 95
            },
            "disk": {
                "keywords": [
                    # Linux 空间使用率（高优先级）
                    "vfs.fs.dependent.size[", ",pused]",
                    # Linux inode（备选）
                    "vfs.fs.dependent.inode[", ",pfree]",
                    # Windows perf_counter
                    "perf_counter[\\logicaldisk", "perf_counter_en[\\logicaldisk",
                    "perf_counter[\\physicaldisk", "perf_counter_en[\\physicaldisk",
                    # 华为存储
                    "huawei.oceanstor.v6.capacity.used",
                    "huawei.oceanstor.v6.lun.bps.total",
                    # Dell 服务器磁盘
                    "dell.server.hw.physicaldisk",
                    # 国产服务器
                    "hardDiskStatus[", "hardDiskEntireStatus",
                    "diskPartitionUsage",
                    # 通用硬件
                    "hardware.disk.usage"
                ],
                "score": 95
            },
            "network": {
                "keywords": [
                    "net.if.in[", "net.if.out[", "net.if.total[",
                    "perf_counter[\\network interface", "perf_counter_en[\\network interface",
                    "huawei.oceanstor.v6.port.bps"
                ],
                "score": 65
            }
        }

        # 降权关键词（避免误伤正常指标）
        demote_keywords = [
            "threshold", "阈值", "预警", "warn", "dynamic", "动态",
            "forecast", "timeleft", "prediction",
            "uptime", "version", "check", "ping"
        ]

        # 优先关键词（带]后缀的优先匹配Zabbix key模式）
        prefer_keywords = ["pused]", "pfree]", "utilization", "usage", "% used"]

        scored_items = []
        for item in items:
            name = item.get("name", "").lower()
            key = item.get("key_", "").lower()
            score = 0
            category = None

            # 分类评分
            for cat, rule in category_rules.items():
                for kw in rule["keywords"]:
                    if kw.lower() in key or kw.lower() in name:
                        score += rule["score"]
                        category = cat
                        break

            if category and score > 0:
                # 优先关键词加分
                for pk in prefer_keywords:
                    if pk in key or pk in name:
                        score += 15

                # 磁盘：优先空间使用率(size)而非inode
                if category == "disk":
                    if "vfs.fs.dependent.size[" in key:
                        score += 20  # 额外加分，优先显示空间使用率
                    elif "vfs.fs.dependent.inode[" in key:
                        score -= 10  # inode降权

                # 内存：优先使用率指标(pused/utilization)而非可用(available)
                if category == "memory":
                    if "pused]" in key or "utilization" in key or "usage" in key:
                        score += 15  # 使用率指标优先
                    elif "available]" in key or "free]" in key:
                        score -= 10  # 可用/剩余空间降权
                    # 降权swap/paging，避免与主内存混淆
                    if "swap" in key or "paging" in key:
                        score -= 40  # 大幅降权swap

                # 降权关键词减分
                for dk in demote_keywords:
                    if dk in key or dk in name:
                        score -= 30

                # 活跃状态加分
                lastvalue = item.get("lastvalue")
                if lastvalue:
                    try:
                        if float(lastvalue) >= 0:
                            score += 10
                    except (TypeError, ValueError):
                        pass

                item["category"] = category
                item["score"] = score
                scored_items.append(item)

        # 按评分降序，每类取最高分（磁盘允许多个）
        category_items = {}
        disk_items = []  # 特殊处理磁盘
        for item in sorted(scored_items, key=lambda x: -x["score"]):
            cat = item["category"]
            if cat == "disk":
                # 磁盘最多取10个（不同盘符），按实际使用率排序
                if len(disk_items) < 10:
                    # 检查是否已存在相同盘符的
                    key = item.get("key_", "")
                    is_duplicate = False
                    for existing in disk_items:
                        existing_key = existing.get("key_", "")
                        # 提取盘符部分进行比较（如 size[C:, -> C:）
                        key_drive = key.split("size[")[1].split(",")[0] if "size[" in key else key
                        existing_drive = existing_key.split("size[")[1].split(",")[0] if "size[" in existing_key else existing_key
                        if key_drive == existing_drive:
                            is_duplicate = True
                            break
                    if not is_duplicate:
                        disk_items.append(item)
            elif cat not in category_items:
                category_items[cat] = item

        # 将磁盘项目加入（按使用率排序，高的在前）
        disk_items_sorted = sorted(
            disk_items,
            key=lambda x: float(x.get("lastvalue", 0)) if x.get("lastvalue") else 0,
            reverse=True
        )
        for disk_item in disk_items_sorted:
            category_items[f"disk_{len([k for k in category_items if k.startswith('disk')])}"] = disk_item

        # 转为分类标签
        category_labels = {
            "cpu": "CPU使用率",
            "memory": "内存使用率",
            "disk": "磁盘使用率",
            "network": "网络流量"
        }

        key_items = []
        for cat, item in category_items.items():
            item["category"] = category_labels.get(cat, cat)
            key_items.append(item)

        if key_items:
            result += "### 关键指标\n"
            result += "| 指标 | 当前值 |\n|------|--------|\n"
            for item in key_items[:10]:  # 最多显示10个
                name = item.get("name", "Unknown")
                value = item.get("lastvalue", "N/A")
                units = item.get("units", "")
                key = item.get("key_", "")

                # 过滤inode项，只保留空间使用率
                if "inode" in key.lower():
                    continue

                # 简化分区名称
                if "FS [" in name:
                    # 提取分区路径，如 FS [/usr]: Space: Used, in % -> /usr分区使用率
                    try:
                        partition = name.split("FS [")[1].split("]")[0]
                        name = f"{partition}分区使用率"
                    except (IndexError, AttributeError):
                        pass

                # 格式化数值
                try:
                    if float(value) > 100 and units == "B":
                        value = f"{float(value)/1024/1024/1024:.2f} GB"
                    elif float(value) < 10:
                        value = f"{float(value):.2f}"
                    else:
                        value = f"{float(value):.1f}"
                except (TypeError, ValueError):
                    pass
                result += f"| {name[:30]} | {value}{units} |\n"
            result += "\n"
        else:
            result += "### 关键指标\n未找到关键性能指标\n\n"
    except Exception as e:
        result += f"### 关键指标\n获取失败: {str(e)}\n\n"

    return result


def _fetch_eventid_pages(
    endpoint: Any,
    base_params: Dict[str, Any],
    page_size: int = QUICK_STATUS_PAGE_SIZE,
    api_label: str = "event.get",
) -> List[Dict[str, Any]]:
    """按 eventid 游标获取完整结果，避免固定 limit 截断统计。"""
    return fetch_all_eventid_pages(endpoint, base_params, page_size, api_label)


def _append_severity_summary(
    result: str,
    title: str,
    rows: List[Dict[str, Any]],
    total_label: str,
    heading_level: int = 3,
) -> str:
    """追加一组按严重级别汇总的 Markdown。"""
    severity_names = {"5": "灾难", "4": "严重", "3": "一般", "2": "警告", "1": "信息", "0": "未分类"}
    severity_icons = {"5": "🚨", "4": "🔴", "3": "🟠", "2": "🟡", "1": "🔵", "0": "⚪"}
    severity_count = {severity: 0 for severity in severity_names}
    for row in rows:
        severity = str(row.get("severity", "0"))
        severity_count[severity] = severity_count.get(severity, 0) + 1

    result += f"{'#' * heading_level} {title}\n"
    for severity in ["5", "4", "3", "2", "1", "0"]:
        count = severity_count.get(severity, 0)
        if count > 0:
            result += f"- {severity_icons[severity]} {severity_names[severity]}: {count}个\n"

    if not rows:
        result += "- 无告警\n"

    result += f"\n**{total_label}: {len(rows)}**\n\n"
    return result


def quick_status(
    include_disabled: Annotated[bool, Field(description="列出停用主机列表（默认False，只显示统计数字）")] = False,
    include_offline: Annotated[bool, Field(description="列出离线主机列表（默认True）")] = True
) -> str:
    """查看主机、统一当前问题分类及最近二十四小时事件。"""
    client = get_zabbix_client()

    try:
        # 1. 主机统计
        # Zabbix 7.0: 可用性字段在 interfaces 中，需要通过 selectInterfaces 获取
        hosts = client.host.get(
            output=["hostid", "host", "name", "status"],
            selectInterfaces=["interfaceid", "available", "type", "ip"],
            limit=10000
        )
        total_hosts = len(hosts)

        # status: 0=启用, 1=禁用
        enabled_hosts = sum(1 for h in hosts if h.get("status") == "0")
        disabled_hosts = sum(1 for h in hosts if h.get("status") == "1")

        # 判断主机在线状态（基于 interfaces 中的 available 字段）
        # interface.available: 1=可用, 2=不可用, 0=未知
        online_hosts = 0
        offline_hosts = 0
        unknown_hosts = 0

        # 收集需要列出的主机
        disabled_host_list = []
        offline_host_list = []

        for h in hosts:
            host_status = h.get("status", "0")
            host_name = h.get("name", "Unknown")
            host_id = h.get("hostid", "N/A")
            interfaces = h.get("interfaces", [])

            # 记录禁用的主机
            if host_status == "1":
                disabled_host_list.append({
                    "hostid": host_id,
                    "name": host_name,
                    "ip": interfaces[0].get("ip", "N/A") if interfaces else "N/A"
                })
                continue

            # 对于启用的主机，判断可用性
            if not interfaces:
                unknown_hosts += 1
                continue

            # 检查所有接口的可用性状态
            has_online = False
            has_offline = False
            offline_ips = []

            for iface in interfaces:
                avail = iface.get("available", "0")
                ip = iface.get("ip", "N/A")
                if avail == "1":
                    has_online = True
                elif avail == "2":
                    has_offline = True
                    offline_ips.append(ip)

            # 判断逻辑并记录离线主机
            if has_online:
                online_hosts += 1
            elif has_offline:
                offline_hosts += 1
                offline_host_list.append({
                    "hostid": host_id,
                    "name": host_name,
                    "ip": offline_ips[0] if offline_ips else (interfaces[0].get("ip", "N/A") if interfaces else "N/A")
                })
            else:
                unknown_hosts += 1

        # 2. 当前问题分类与最近24小时历史问题事件分别统计
        now = int(time.time())
        current_summary = analyze_current_problems(client, analysis_clock=now)
        actionable = current_summary.by_status(AttentionStatus.ACTIONABLE)
        handled = current_summary.by_status(AttentionStatus.HANDLED_ACTIVE)
        ended = current_summary.by_status(AttentionStatus.ENDED)
        recent_events = _fetch_eventid_pages(
            client.event,
            {
                "source": 0,
                "object": 0,
                "value": 1,
                "time_from": now - 86400,
                "time_till": now,
                "output": ["eventid", "severity"],
            },
        )

        # 3. 构建报告
        result = "## Zabbix 整体状态\n\n"

        result += "### 主机状态\n"
        result += f"- **总数**: {total_hosts} 台\n"
        result += f"- **启用**: {enabled_hosts} 台（在线 {online_hosts} / 离线 {offline_hosts} / 未知 {unknown_hosts}）\n"
        result += f"- **停用**: {disabled_hosts} 台\n\n"

        # 计算可用率（基于启用主机）
        if enabled_hosts > 0:
            availability_rate = (online_hosts / enabled_hosts) * 100
            result += f"> 主机可用率: **{availability_rate:.1f}%** ({online_hosts}/{enabled_hosts})\n\n"

        # 4. 列出停用主机
        if include_disabled and disabled_host_list:
            result += f"### 停用主机（{len(disabled_host_list)} 台）\n"
            result += "| 主机名 | IP地址 |\n"
            result += "|--------|--------|\n"
            for h in disabled_host_list[:20]:  # 最多显示20台
                # 截断长名称
                name = h["name"][:40] if len(h["name"]) > 40 else h["name"]
                result += f"| {name} | {h['ip']} |\n"
            if len(disabled_host_list) > 20:
                result += f"| ... 还有 {len(disabled_host_list) - 20} 台 | ... |\n"
            result += "\n"

        # 5. 列出离线主机
        if include_offline and offline_host_list:
            result += f"### 离线主机（{len(offline_host_list)} 台）\n"
            result += "| 主机名 | IP地址 |\n"
            result += "|--------|--------|\n"
            for h in offline_host_list:
                # 截断长名称
                name = h["name"][:40] if len(h["name"]) > 40 else h["name"]
                result += f"| {name} | {h['ip']} |\n"
            result += "\n"

        # 6. 当前问题分类
        result += "### 当前问题分类\n"
        result += f"- Zabbix 原始当前问题: {current_summary.raw_count}\n"
        result += f"- 当前需处理: {len(actionable)}\n"
        result += f"- 已处置但仍在触发: {len(handled)}\n"
        if ended:
            result += f"- 已结束: {len(ended)}\n"
        result += "\n"

        result = _append_severity_summary(
            result,
            "当前需处理严重级别",
            [{"severity": fact.severity} for fact in actionable],
            "当前需处理总计",
            heading_level=4,
        )
        result = _append_severity_summary(
            result,
            "已处置但仍在触发严重级别",
            [{"severity": fact.severity} for fact in handled],
            "已处置但仍在触发总计",
            heading_level=4,
        )

        handled_by_disposition = {
            disposition: sum(fact.disposition_status == disposition for fact in handled)
            for disposition in (
                DispositionStatus.ACKNOWLEDGED,
                DispositionStatus.SUPPRESSED,
                DispositionStatus.ACKNOWLEDGED_AND_SUPPRESSED,
            )
        }
        result += "#### 已处置但仍在触发的处置类型\n"
        result += f"- 已确认: {handled_by_disposition[DispositionStatus.ACKNOWLEDGED]}\n"
        result += f"- 已人工抑制: {handled_by_disposition[DispositionStatus.SUPPRESSED]}\n"
        result += f"- 已确认且已人工抑制: {handled_by_disposition[DispositionStatus.ACKNOWLEDGED_AND_SUPPRESSED]}\n\n"
        result += "> 上述问题已有人工处置，但技术状态仍在触发，不代表真实恢复。\n\n"

        # 7. 最近二十四小时事件统计
        result = _append_severity_summary(
            result,
            "最近24小时实际发生的问题事件",
            recent_events,
            "事件总计",
        )

        return result.rstrip()

    except Exception as e:
        return f"获取整体状态失败: {str(e)}"


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


def host_alert_history(
    hostid: Annotated[Union[str, int], Field(description="主机ID")],
    triggerid: Annotated[Union[str, int], Field(description="触发器ID")],
    days: Annotated[int, Field(description=f"查询天数（默认{DEFAULT_QUERY_DAYS}）")] = DEFAULT_QUERY_DAYS,
) -> HostAlertHistoryResult:
    """查询完整分页、精确恢复配对的主机与触发器告警历史。"""
    normalized_hostid = str(hostid)
    normalized_triggerid = str(triggerid)
    if days <= 0:
        return _empty_host_alert_history(
            normalized_triggerid,
            complete=False,
            error="days 必须大于 0",
        )

    client = get_zabbix_client()
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
