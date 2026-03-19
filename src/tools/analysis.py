"""Analysis Tools - MCP tools for data analysis and summaries."""
import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from client import get_zabbix_client
from utils.params import parse_int_param, parse_list_param, parse_dict_param, parse_time_param
from utils.format import format_response, format_table

logger = logging.getLogger(__name__)


def trend_get(
    itemids: Union[List[str], str],
    time_from: Union[int, str, None] = None,
    time_till: Union[int, str, None] = None,
    limit: Union[int, str, None] = 24
) -> str:
    """Get trend data from Zabbix.

    Args:
        itemids: List of item IDs to get trends for
        time_from: Start time (Unix timestamp)
        time_till: End time (Unix timestamp)
        limit: Maximum number of results

    Returns:
        str: JSON formatted trend data
    """
    itemids = parse_list_param(itemids)
    limit = parse_int_param(limit, 24)
    time_from = parse_int_param(time_from)
    time_till = parse_int_param(time_till)

    client = get_zabbix_client()
    params = {
        "itemids": itemids,
        "limit": limit
    }

    if time_from:
        params["time_from"] = time_from
    if time_till:
        params["time_till"] = time_till

    result = client.trend.get(**params)
    return format_response(result)


def trend_summary(
    itemids: Union[str, List[str]],
    hours: int = 24,
    include_analysis: bool = True
) -> str:
    """获取趋势统计摘要（极省Token），适合快速了解指标变化。

    相比 trend_get（返回详细时间序列），trend_summary 只返回：
    - 当前值、平均值/最大值/最小值
    - 趋势判断（上升/下降/平稳）
    - 关键时间点

    Args:
        itemids: 监控项ID（最多3个，防止Token溢出）
        hours: 查询时长（默认24小时）
        include_analysis: 是否包含趋势分析和建议

    Returns:
        Markdown格式摘要
    """
    client = get_zabbix_client()

    # 解析itemids
    if isinstance(itemids, str):
        # 先尝试按逗号分隔（LLM常传递 "68053,68050,499673" 格式）
        if ',' in itemids:
            itemids = [i.strip() for i in itemids.split(',') if i.strip()]
        else:
            try:
                itemids = json.loads(itemids)
                if not isinstance(itemids, list):
                    itemids = [itemids]
            except:
                itemids = [itemids]

    # 限制数量
    if len(itemids) > 3:
        itemids = itemids[:3]

    # 计算时间范围
    time_till = int(time.time())
    time_from = time_till - (hours * 3600)

    try:
        # 获取趋势数据
        trends = client.trend.get(
            itemids=itemids,
            time_from=time_from,
            time_till=time_till,
            output=["itemid", "value_avg", "value_max", "value_min", "clock"]
        )

        if not trends:
            return f"【调试】trends为空。查询参数：itemids={itemids}, time_from={time_from}, time_till={time_till}"

        # 收集实际返回的itemids用于调试
        returned_itemids = list(set(str(t.get("itemid", "")) for t in trends if t.get("itemid")))

        # 按itemid分组统计
        from collections import defaultdict
        item_stats = defaultdict(lambda: {"values": [], "max_val": 0, "min_val": float('inf'), "max_time": ""})

        for t in trends:
            itemid = str(t.get("itemid", ""))  # 转为字符串
            if not itemid:
                continue
            try:
                val = float(t.get("value_avg", 0))
                max_val = float(t.get("value_max", 0))
                min_val = float(t.get("value_min", 0))
                clock = int(t.get("clock", 0))

                item_stats[itemid]["values"].append(val)
                if max_val > item_stats[itemid]["max_val"]:
                    item_stats[itemid]["max_val"] = max_val
                    item_stats[itemid]["max_time"] = datetime.fromtimestamp(clock).strftime("%H:%M")
                if min_val < item_stats[itemid]["min_val"]:
                    item_stats[itemid]["min_val"] = min_val
            except:
                continue

        # 获取监控项信息
        items_info = client.item.get(
            itemids=itemids,
            output=["itemid", "name", "units"]
        )
        item_names = {str(i["itemid"]): {"name": i["name"], "units": i.get("units", "")} for i in items_info}

        # 构建结果
        rows = []
        analyses = []

        for itemid in itemids:
            itemid_str = str(itemid)  # 转为字符串
            stats = item_stats.get(itemid_str)
            if not stats or not stats["values"]:
                continue

            info = item_names.get(itemid_str, {"name": itemid_str, "units": ""})
            values = stats["values"]

            current = values[-1]
            avg = sum(values) / len(values)
            max_val = stats["max_val"]
            min_val = stats["min_val"]
            max_time = stats["max_time"]

            # 趋势判断
            mid = len(values) // 2
            first_half = sum(values[:mid]) / mid if mid > 0 else avg
            second_half = sum(values[mid:]) / (len(values) - mid) if mid < len(values) else avg

            if second_half > first_half * 1.1:
                trend = "上升"
            elif second_half < first_half * 0.9:
                trend = "下降"
            else:
                trend = "平稳"

            units = info.get("units", "")
            rows.append([
                info["name"][:20],
                f"{current:.1f}{units}",
                f"{avg:.1f}",
                f"{max_val:.1f} ({max_time})",
                f"{min_val:.1f}",
                trend
            ])

            if include_analysis:
                if trend == "上升":
                    analyses.append(f"- **{info['name'][:20]}**: 呈上升趋势，建议关注")
                elif max_val > avg * 1.5:
                    analyses.append(f"- **{info['name'][:20]}**: 波动较大，峰值达到 {max_val:.1f}")

        # 格式化输出
        if not rows:
            # 返回详细调试信息
            debug_info = f"""【调试信息】
- 查询的itemids: {itemids}
- Zabbix返回的趋势数据条数: {len(trends)}
- 返回数据中的itemids: {returned_itemids}
- 处理后有数据的itemids: {list(item_stats.keys())}
- 监控项查询结果: {len(items_info)}个
"""
            return debug_info

        result = f"## 趋势摘要（最近{hours}小时）\n\n"
        result += format_table(
            ["监控项", "当前值", "平均值", "最大值", "最小值", "趋势"],
            rows
        )

        if include_analysis and analyses:
            result += "\n### 分析\n" + "\n".join(analyses[:3])

        return result

    except Exception as e:
        return f"趋势摘要生成失败: {str(e)}"


def get_problem_summary(
    hostids: Optional[str] = None,
    time_range: str = "24h",
    group_by: str = "severity"
) -> str:
    """获取告警摘要（已聚合），适合对话场景直接展示。

    Args:
        hostids: 主机ID（可选，逗号分隔）
        time_range: 时间范围，支持 "1h", "24h", "7d"
        group_by: 分组方式（默认按严重程度）

    Returns:
        Markdown格式告警摘要
    """
    client = get_zabbix_client()

    # 解析时间
    now = int(time.time())
    if time_range == "1h":
        time_from = now - 3600
    elif time_range == "24h":
        time_from = now - 86400
    elif time_range == "7d":
        time_from = now - 604800
    else:
        time_from = now - 86400

    # 解析hostids
    hostid_list = None
    if hostids:
        hostid_list = [h.strip() for h in hostids.split(",") if h.strip()]

    try:
        # 获取告警
        params = {
            "output": ["eventid", "name", "severity", "clock", "objectid"],
            "time_from": time_from,
            "sortfield": "eventid",
            "sortorder": "DESC",
            "limit": 100
        }
        if hostid_list:
            params["hostids"] = hostid_list

        problems = client.problem.get(**params)

        if not problems:
            return f"## 告警概览\n\n**{time_range} 内无活跃告警**"

        # 统计
        severity_names = {
            "0": "未分类", "1": "信息", "2": "警告",
            "3": "一般", "4": "严重", "5": "灾难"
        }
        severity_icons = {
            "0": "⚪", "1": "🔵", "2": "🟡",
            "3": "🟠", "4": "🔴", "5": "🚨"
        }

        stats = {}
        for p in problems:
            sev = str(p.get("severity", "0"))
            stats[sev] = stats.get(sev, 0) + 1

        # 获取主机信息
        trigger_ids = list(set([p.get("objectid") for p in problems if p.get("objectid")]))
        host_map = {}
        if trigger_ids:
            triggers = client.trigger.get(
                triggerids=trigger_ids,
                output=["triggerid"],
                selectHosts=["hostid", "name"]
            )
            for t in triggers:
                if t.get("hosts"):
                    host_map[t["triggerid"]] = t["hosts"][0].get("name", "Unknown")

        # 构建Markdown
        total = len(problems)
        result = f"## 告警概览 ({time_range})\n\n"
        result += f"**总计: {total} 个告警**\n\n"

        # 按级别统计
        for sev in ["5", "4", "3", "2", "1", "0"]:
            if sev in stats:
                result += f"{severity_icons[sev]} {severity_names[sev]}: {stats[sev]}个\n"

        # Top 5详情
        result += "\n### 最严重的5个告警\n"
        result += "| 时间 | 主机 | 问题 | 级别 |\n"
        result += "|------|------|------|------|\n"

        top5 = sorted(problems, key=lambda x: int(x.get("severity", 0)), reverse=True)[:5]
        for p in top5:
            clock = int(p.get("clock", 0))
            time_str = datetime.fromtimestamp(clock).strftime("%m-%d %H:%M")
            host = host_map.get(p.get("objectid", ""), "Unknown")[:15]
            name = p.get("name", "Unknown")[:25]
            sev = str(p.get("severity", "0"))
            result += f"| {time_str} | {host} | {name} | {severity_icons[sev]} |\n"

        return result

    except Exception as e:
        return f"获取告警摘要失败: {str(e)}"


def check_host_health(
    host_identifier: str,
    time_range: str = "24h",
    include_trends: bool = False,
    trend_hours: int = 24,
    include_oracle: bool = False
) -> str:
    """一站式检查主机健康状况。

    Args:
        host_identifier: 主机标识（IP/主机名/hostid）
        time_range: 查询告警的时间范围
        include_trends: 是否包含趋势数据
        trend_hours: 趋势数据查询时长
        include_oracle: 是否查询Oracle相关指标

    Returns:
        Markdown格式健康报告
    """
    client = get_zabbix_client()

    # 1. 识别主机
    hostid = None
    host_name = host_identifier

    # 尝试作为hostid
    try:
        hosts = client.host.get(
            hostids=[host_identifier],
            output=["hostid", "name", "available", "status"]
        )
        if hosts:
            hostid = hosts[0]["hostid"]
            host_name = hosts[0].get("name", host_identifier)
    except:
        pass

    # 尝试作为IP
    if not hostid:
        try:
            interfaces = client.hostinterface.get(
                filter={"ip": host_identifier},
                output=["hostid"]
            )
            if interfaces:
                hostid = interfaces[0]["hostid"]
                hosts = client.host.get(
                    hostids=[hostid],
                    output=["hostid", "name", "available", "status"]
                )
                if hosts:
                    host_name = hosts[0].get("name", host_identifier)
        except:
            pass

    # 尝试作为主机名模糊搜索（支持部分匹配）
    if not hostid:
        try:
            # 方法1: 使用 filter 精确匹配（如果 host_identifier 就是完整名称）
            hosts = client.host.get(
                filter={"name": host_identifier},
                output=["hostid", "name", "available", "status"],
                limit=1
            )
            if hosts:
                hostid = hosts[0]["hostid"]
                host_name = hosts[0].get("name", host_identifier)
        except:
            pass

    # 方法2: 使用 search 子串搜索（不需要通配符，search 默认就是子串匹配）
    if not hostid:
        try:
            hosts = client.host.get(
                search={"name": host_identifier},
                searchWildcardsEnabled=False,
                output=["hostid", "name", "available", "status"],
                limit=1
            )
            if hosts:
                hostid = hosts[0]["hostid"]
                host_name = hosts[0].get("name", host_identifier)
        except:
            pass

    # 方法3: 尝试提取 IP 地址进行匹配
    if not hostid:
        import re
        ip_pattern = r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
        ip_match = re.search(ip_pattern, host_identifier)
        if ip_match:
            try:
                ip = ip_match.group(1)
                interfaces = client.hostinterface.get(
                    filter={"ip": ip},
                    output=["hostid"]
                )
                if interfaces:
                    hostid = interfaces[0]["hostid"]
                    hosts = client.host.get(
                        hostids=[hostid],
                        output=["hostid", "name", "available", "status"]
                    )
                    if hosts:
                        host_name = hosts[0].get("name", host_identifier)
            except:
                pass

    if not hostid:
        return f"未找到主机: {host_identifier}"

    # 2. 获取主机信息
    host_info = hosts[0] if hosts else {}
    available = host_info.get("available", "0")
    status_map = {"0": "Agent正常", "1": "Agent异常", "2": "未知"}
    status_icon = {"0": "正常", "1": "异常", "2": "未知"}

    result = f"## 主机: {host_name}\n\n"
    result += f"- 状态: {status_icon.get(available, '未知')}\n"
    result += f"- HostID: {hostid}\n\n"

    # 3. 获取告警
    try:
        now = int(time.time())
        time_from = now - (24 * 3600)  # 默认24小时

        problems = client.problem.get(
            hostids=[hostid],
            time_from=time_from,
            output=["name", "severity", "clock"],
            limit=10
        )

        if problems:
            result += "### 当前告警\n"
            severity_icons = {"5": "🚨", "4": "🔴", "3": "🟠", "2": "🟡", "1": "🔵", "0": "⚪"}
            for p in problems:
                sev = str(p.get("severity", "0"))
                name = p.get("name", "Unknown")
                result += f"- {severity_icons.get(sev, '⚪')} {name}\n"
            result += "\n"
        else:
            result += "### 当前告警\n无活跃告警\n\n"
    except Exception as e:
        result += f"### 当前告警\n获取失败: {str(e)}\n\n"

    # 4. 获取关键指标
    try:
        # 获取主机的所有监控项（使用智能评分算法）
        items = client.item.get(
            hostids=[hostid],
            output=["itemid", "name", "key_", "lastvalue", "units", "lastclock"],
            limit=1000
        )

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
                    except:
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
                    except:
                        pass

                # 格式化数值
                try:
                    if float(value) > 100 and units == "B":
                        value = f"{float(value)/1024/1024/1024:.2f} GB"
                    elif float(value) < 10:
                        value = f"{float(value):.2f}"
                    else:
                        value = f"{float(value):.1f}"
                except:
                    pass
                result += f"| {name[:30]} | {value}{units} |\n"
            result += "\n"
        else:
            result += "### 关键指标\n未找到关键性能指标\n\n"
    except Exception as e:
        result += f"### 关键指标\n获取失败: {str(e)}\n\n"

    return result


def quick_status(include_disabled: bool = True, include_offline: bool = True) -> str:
    """快速查看Zabbix整体状态 - 适合每日巡检。

    Args:
        include_disabled: 是否列出禁用主机列表
        include_offline: 是否列出离线主机列表

    Returns:
        Markdown格式状态摘要
    """
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

        # 2. 告警统计
        now = int(time.time())
        problems = client.problem.get(
            time_from=now - 86400,
            output=["severity"],
            limit=1000
        )

        severity_count = {"5": 0, "4": 0, "3": 0, "2": 0, "1": 0, "0": 0}
        for p in problems:
            sev = str(p.get("severity", "0"))
            severity_count[sev] = severity_count.get(sev, 0) + 1

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

        # 6. 告警统计
        result += "### 24小时告警统计\n"
        severity_names = {"5": "灾难", "4": "严重", "3": "一般", "2": "警告", "1": "信息", "0": "未分类"}
        severity_icons = {"5": "🚨", "4": "🔴", "3": "🟠", "2": "🟡", "1": "🔵", "0": "⚪"}

        has_problems = False
        for sev in ["5", "4", "3", "2", "1", "0"]:
            count = severity_count.get(sev, 0)
            if count > 0:
                has_problems = True
                result += f"- {severity_icons[sev]} {severity_names[sev]}: {count}个\n"

        if not has_problems:
            result += "- 无告警\n"

        total_problems = sum(severity_count.values())
        result += f"\n**告警总计: {total_problems}**\n"

        return result

    except Exception as e:
        return f"获取整体状态失败: {str(e)}"
