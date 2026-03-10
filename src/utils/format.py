"""格式化输出工具"""
import json
from typing import Any, List, Dict, Optional


def format_response(data: Any) -> str:
    """格式化响应数据为JSON字符串"""
    return json.dumps(data, ensure_ascii=False, indent=2)


def format_table(headers: List[str], rows: List[List[str]]) -> str:
    """
    格式化为Markdown表格

    Args:
        headers: 表头列表
        rows: 行数据列表

    Returns:
        Markdown格式的表格字符串
    """
    if not rows:
        return "暂无数据"

    # 计算每列最大宽度
    col_widths = []
    for i, header in enumerate(headers):
        max_width = len(str(header))
        for row in rows:
            if i < len(row):
                max_width = max(max_width, len(str(row[i])))
        col_widths.append(max_width)

    lines = []

    # 表头
    header_row = " | ".join(
        str(h).ljust(col_widths[i]) for i, h in enumerate(headers)
    )
    lines.append(f"| {header_row} |")

    # 分隔线
    separator = " | ".join("-" * w for w in col_widths)
    lines.append(f"| {separator} |")

    # 数据行
    for row in rows:
        row_str = " | ".join(
            str(row[i] if i < len(row) else "").ljust(col_widths[i])
            for i in range(len(headers))
        )
        lines.append(f"| {row_str} |")

    return "\n".join(lines)


def format_problem_summary(problems: List[Dict]) -> str:
    """
    格式化告警摘要，适合对话展示

    Args:
        problems: 告警列表

    Returns:
        格式化的摘要字符串
    """
    if not problems:
        return "✅ 当前没有告警"

    # 按严重程度分组统计
    severity_map = {
        0: ("🔵 未分类", 0),
        1: ("🟢 信息", 0),
        2: ("🟡 警告", 0),
        3: ("🟠 一般", 0),
        4: ("🔴 严重", 0),
        5: ("🔴🔴 灾难", 0),
    }

    for p in problems:
        sev = p.get("priority", 0)
        if sev in severity_map:
            label, count = severity_map[sev]
            severity_map[sev] = (label, count + 1)

    lines = ["## 告警概览\n"]

    # 统计摘要
    total = len(problems)
    lines.append(f"**总计: {total} 个告警**\n")

    for sev in sorted(severity_map.keys(), reverse=True):
        label, count = severity_map[sev]
        if count > 0:
            lines.append(f"{label}: {count}个")

    lines.append("")

    # 详细列表（只展示最严重的5个）
    if problems:
        lines.append("### 最严重的5个告警\n")

        headers = ["时间", "主机", "问题", "级别"]
        rows = []

        for p in sorted(problems, key=lambda x: x.get("priority", 0), reverse=True)[:5]:
            # 格式化时间
            ts = p.get("lastchange", "")
            if ts:
                from datetime import datetime
                try:
                    dt = datetime.fromtimestamp(int(ts))
                    time_str = dt.strftime("%m-%d %H:%M")
                except:
                    time_str = str(ts)
            else:
                time_str = "-"

            host = p.get("hosts", [{}])[0].get("name", "未知") if p.get("hosts") else "未知"
            desc = p.get("description", "无描述")[:30]  # 截断

            sev = p.get("priority", 0)
            sev_label = {5: "灾难", 4: "严重", 3: "一般", 2: "警告", 1: "信息"}.get(sev, "未分类")

            rows.append([time_str, host, desc, sev_label])

        lines.append(format_table(headers, rows))

    return "\n".join(lines)


def format_host_overview(host: Dict, problems: List[Dict], items: List[Dict]) -> str:
    """
    格式化主机概览

    Args:
        host: 主机信息
        problems: 告警列表
        items: 监控项列表

    Returns:
        格式化的概览字符串
    """
    lines = []

    # 主机基本信息
    host_name = host.get("name", "未知")
    host_ip = host.get("interfaces", [{}])[0].get("ip", "N/A") if host.get("interfaces") else "N/A"
    status = "🟢 正常" if host.get("available") == "1" else "🔴 不可用"

    lines.append(f"## 🖥️ {host_name}")
    lines.append(f"- IP: {host_ip}")
    lines.append(f"- 状态: {status}")
    lines.append("")

    # 告警摘要
    if problems:
        lines.append(f"### ⚠️ 告警 ({len(problems)}个)")
        for p in problems[:3]:  # 只展示前3个
            desc = p.get("description", "无描述")
            sev = p.get("priority", 0)
            sev_emoji = {5: "🔴🔴", 4: "🔴", 3: "🟠", 2: "🟡", 1: "🟢"}.get(sev, "⚪")
            lines.append(f"{sev_emoji} {desc}")
        lines.append("")
    else:
        lines.append("✅ 无告警\n")

    # 关键指标
    key_metrics = {}
    for item in items:
        key = item.get("key_", "")
        if "cpu.util" in key:
            key_metrics["CPU"] = item.get("lastvalue", "N/A")
        elif "memory.util" in key or "vm.memory.util" in key:
            key_metrics["内存"] = item.get("lastvalue", "N/A")
        elif "vfs.fs.size" in key and "pused" in key:
            key_metrics["磁盘"] = item.get("lastvalue", "N/A")

    if key_metrics:
        lines.append("### 📊 关键指标")
        for name, value in key_metrics.items():
            lines.append(f"- {name}: {value}%")

    return "\n".join(lines)
