"""摘要工具 - 为Dify/LLM优化的查询接口"""
import os
from typing import Optional, List
from fastmcp import FastMCP
from ..utils.params import parse_time_param, parse_list_param
from ..utils.format import format_problem_summary, format_host_overview, format_table

mcp = FastMCP("Zabbix MCP Server")


@mcp.tool()
def get_problem_summary(
    hostids: Optional[str] = None,
    time_range: str = "24h",
    group_by: str = "severity"
) -> str:
    """
    获取告警摘要（已聚合），适合对话场景直接展示

    比 problem_get 更适合LLM展示，返回Markdown格式，无需二次处理

    Args:
        hostids: 主机ID列表（逗号分隔或JSON数组），不传则查询全部
        time_range: 时间范围，支持 "1h", "24h", "7d", "yesterday"
        group_by: 分组方式，默认按严重程度

    Returns:
        Markdown格式的告警摘要，包含统计和详情

    Example:
        get_problem_summary(time_range="24h")
        get_problem_summary(hostids="10084,10085", time_range="1h")
    """
    # 导入客户端（避免循环导入）
    from ..client import get_zabbix_client

    client = get_zabbix_client()

    # 解析参数
    hostid_list = parse_list_param(hostids)

    # 计算时间
    now = int(__import__('time').time())
    time_from = parse_time_param(time_range, now - 86400)  # 默认24小时

    # 构建查询参数
    params = {
        "output": ["eventid", "name", "severity", "clock", "objectid"],
        "selectHosts": ["hostid", "name"],
        "sortfield": "severity",
        "sortorder": "DESC",
        "time_from": time_from
    }

    if hostid_list:
        params["hostids"] = hostid_list

    # 查询
    problems = client.problem.get(**params)

    return format_problem_summary(problems)


@mcp.tool()
def check_host_health(host_identifier: str, time_range: str = "1h") -> str:
    """
    一站式检查主机健康状况 - 适合"帮我看看XX服务器怎么样"这种场景

    自动识别 host_identifier 类型（IP/主机名/hostid），返回完整的健康报告

    Args:
        host_identifier: 主机标识（IP地址、主机名或hostid）
        time_range: 查询时间范围，默认1小时

    Returns:
        Markdown格式的健康报告，包含：
        - 主机基本信息
        - 当前告警
        - 关键指标（CPU/内存/磁盘）
        - 健康建议

    Example:
        check_host_health("172.18.6.220")
        check_host_health("情报系统应用服务器")
    """
    from ..client import get_zabbix_client
    from ..utils.params import parse_time_param

    client = get_zabbix_client()

    # 1. 识别并查找hostid
    hostid = _resolve_host_identifier(client, host_identifier)
    if not hostid:
        return f"❌ 未找到主机: {host_identifier}，请检查主机名或IP是否正确"

    # 2. 获取主机信息
    hosts = client.host.get(
        hostids=[hostid],
        output=["hostid", "name", "available", "error", "status"],
        selectInterfaces=["ip", "dns"]
    )
    if not hosts:
        return f"❌ 无法获取主机信息: {host_identifier}"

    host = hosts[0]

    # 3. 获取告警
    problems = client.problem.get(
        hostids=[hostid],
        output=["eventid", "name", "severity", "clock", "description"],
        selectHosts=["name"]
    )

    # 4. 获取关键监控项
    items = client.item.get(
        hostids=[hostid],
        search={"key_": ["system.cpu.util", "vm.memory.util", "vfs.fs.size"]},
        output=["itemid", "name", "key_", "lastvalue", "units"]
    )

    return format_host_overview(host, problems, items)


@mcp.tool()
def quick_status() -> str:
    """
    快速查看Zabbix整体状态 - 适合每日巡检

    Returns:
        整体状态摘要，包含：
        - 主机总数和在线状态
        - 告警统计
        - 最近事件
    """
    from ..client import get_zabbix_client

    client = get_zabbix_client()

    lines = ["# Zabbix 整体状态\n"]

    # 1. 主机统计
    hosts = client.host.get(
        output=["hostid", "available"],
        filter={"status": 0}  # 只统计启用状态的主机
    )
    total = len(hosts)
    online = sum(1 for h in hosts if h.get("available") == "1")

    lines.append(f"## 🖥️ 主机状态")
    lines.append(f"- 总数: {total}")
    lines.append(f"- 🟢 在线: {online}")
    lines.append(f"- 🔴 离线: {total - online}")
    lines.append("")

    # 2. 告警统计
    problems = client.problem.get(
        output=["severity"],
        sortfield="severity",
        sortorder="DESC"
    )

    lines.append(f"## ⚠️ 告警统计")
    if problems:
        severity_count = {}
        for p in problems:
            sev = p.get("severity", 0)
            severity_count[sev] = severity_count.get(sev, 0) + 1

        for sev in sorted(severity_count.keys(), reverse=True):
            emoji = {5: "🔴🔴", 4: "🔴", 3: "🟠", 2: "🟡"}.get(sev, "⚪")
            name = {5: "灾难", 4: "严重", 3: "一般", 2: "警告"}.get(sev, "其他")
            lines.append(f"{emoji} {name}: {severity_count[sev]}个")
    else:
        lines.append("✅ 当前无告警")

    return "\n".join(lines)


def _resolve_host_identifier(client, identifier: str) -> Optional[str]:
    """
    解析主机标识符，返回hostid

    支持：
    1. 纯数字（认为是hostid）
    2. IP地址格式（搜索interfaces）
    3. 主机名（模糊搜索）
    """
    # 1. 检查是否是纯数字（hostid）
    if identifier.isdigit():
        return identifier

    # 2. 检查是否是IP地址
    import re
    ip_pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
    if re.match(ip_pattern, identifier):
        interfaces = client.hostinterface.get(
            output=["hostid"],
            filter={"ip": identifier}
        )
        if interfaces:
            return interfaces[0]["hostid"]
        return None

    # 3. 按主机名搜索（模糊匹配）
    hosts = client.host.get(
        output=["hostid", "name"],
        search={"name": identifier},
        searchWildcardsEnabled=True,
        limit=5
    )

    if len(hosts) == 1:
        return hosts[0]["hostid"]
    elif len(hosts) > 1:
        # 如果有多个匹配，返回第一个并记录警告
        # 实际使用时可以让LLM询问用户选择哪个
        return hosts[0]["hostid"]

    return None
