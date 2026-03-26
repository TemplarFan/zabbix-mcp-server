"""Query Tools - MCP tools for basic data queries."""
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from client import get_zabbix_client
from utils.params import parse_int_param, parse_list_param, parse_dict_param, parse_time_param
from utils.format import format_response

logger = logging.getLogger(__name__)


def _format_events_as_table(events: list) -> str:
    """Format events list as markdown table for better display."""
    if not events:
        return "暂无事件数据"

    lines = ["| 时间 | 主机 | 问题 | 级别 |", "|------|------|------|------|"]

    severity_names = {"0": "未分类", "1": "信息", "2": "警告", "3": "一般", "4": "严重", "5": "灾难"}

    for event in events:
        clock = event.get("clock", 0)
        try:
            from datetime import datetime
            time_str = datetime.fromtimestamp(int(clock)).strftime("%m-%d %H:%M")
        except:
            time_str = str(clock)

        hosts = event.get("hosts", [{}])
        host_name = hosts[0].get("name", "Unknown") if hosts else "Unknown"

        name = event.get("name", "Unknown")
        severity = str(event.get("severity", "0"))
        sev_name = severity_names.get(severity, severity)

        lines.append(f"| {time_str} | {host_name} | {name} | {sev_name} |")

    return "\n".join(lines)


def host_get(
    hostids: Union[List[str], str, None] = None,
    name: Optional[str] = None,
    groupids: Union[List[str], str, None] = None,
    templateids: Union[List[str], str, None] = None,
    output: Union[str, List[str], None] = None,
    search: Union[Dict[str, str], str, None] = None,
    filter: Union[Dict[str, Any], str, None] = None,
    limit: Union[int, str, None] = 10
) -> str:
    """获取主机信息列表。支持通过ID精确查询或通过名称模糊查询。

    详细说明：查询 Zabbix 监控中的主机信息，支持多种查询方式：
    - 通过 hostids 精确查询特定主机
    - 通过 name 参数进行主机名模糊匹配（支持通配符）
    - 通过 groupids 筛选特定主机组
    - 通过 templateids 筛选使用特定模板的主机

    与 get_host_by_ip 的区别：
    - host_get：通用查询，支持多种条件组合
    - get_host_by_ip：通过IP地址精确定位，更节省Token

    Args:
        hostids: 主机ID列表（可选，支持单个ID或逗号分隔的多个ID）
        name: 主机名关键词（可选），支持模糊匹配
              例如：输入"情报"可匹配"情报系统应用服务器"
        groupids: 主机组ID列表（可选），用于筛选特定主机组
        templateids: 模板ID列表（可选），用于筛选使用特定模板的主机
        output: 返回字段列表（可选），默认为核心字段 ["hostid", "host", "name", "status", "available"]
        search: 搜索条件字典（可选），如 {"name": "server"}
        filter: 过滤条件字典（可选），如 {"status": "0"}
        limit: 最大返回数量（可选，默认10条），防止数据过载

    Returns:
        JSON格式的主机信息列表，包含 hostid、host、name、status、available 等字段
        如果结果达到限制数量，会提示"仅显示前 N 个匹配结果"

    使用场景：
        - 场景1：通过主机ID精确查询
          host_get(hostids="12345")
        - 场景2：通过名称模糊搜索
          host_get(name="web")
        - 场景3：查询特定主机组的主机
          host_get(groupids="10", limit=50)
        - 场景4：已知IP时（更推荐用 get_host_by_ip）
          get_host_by_ip(ip="192.168.1.1")
    """
    client = get_zabbix_client()

    # 1. 解析参数
    hostids = parse_list_param(hostids)
    groupids = parse_list_param(groupids)
    templateids = parse_list_param(templateids)
    search = parse_dict_param(search) or {}
    filter = parse_dict_param(filter)
    limit = parse_int_param(limit, 10)

    # 2. 核心逻辑：处理模糊匹配
    if name:
        search["name"] = f"*{name}*"

    # 3. 默认输出字段
    if output is None:
        output = ["hostid", "host", "name", "status", "available"]

    params = {
        "output": output,
        "limit": limit,
        "searchWildcardsEnabled": True,
        "searchByAny": True
    }

    if hostids:
        params["hostids"] = hostids
    if groupids:
        params["groupids"] = groupids
    if templateids:
        params["templateids"] = templateids
    if search:
        params["search"] = search
    if filter:
        params["filter"] = filter

    try:
        result = client.host.get(**params)

        if not result:
            search_info = name if name else (str(search) if search else '无')
            return f"未找到匹配项。搜索关键词: {search_info}"

        if len(result) >= limit:
            hint = f"\n(注意：仅显示前 {limit} 个匹配结果，请提供更精确的名称以缩小范围)"
            return format_response(result) + hint

        return format_response(result)
    except Exception as e:
        return f"查询过程中出现异常: {str(e)}"


def item_get(
    itemids: Union[List[str], str, None] = None,
    hostids: Union[List[str], str, None] = None,
    search: Union[Dict[str, str], str, None] = None,
    limit: Union[int, str, None] = None,
    output: Any = None,
    key_metrics_only: bool = False
) -> str:
    """获取监控项。支持 memory/cpu 等语义联想搜索，解决搜不到的问题。

    使用场景：
    1. 查询特定监控项（传 itemids）
    2. 查询主机的所有监控项（传 hostids）
    3. 查询主机的关键性能指标（传 hostids + key_metrics_only=true）
       关键指标包括：CPU使用率、内存使用率、磁盘使用率，每个类别只返回1个最佳指标

    重要提示：Zabbix API 不支持 offset 翻页，只能用 limit 限制返回数量。
    如需查看更多监控项，请使用 search 参数过滤（如搜索 "disk"、"memory" 等关键词）。

    Args:
        itemids: 监控项ID列表
        hostids: 主机ID列表
        search: 搜索条件（如 {"name": "cpu"}）
        limit: 返回数量限制（默认20）
        output: 输出字段
        key_metrics_only: 仅返回关键性能指标（CPU/内存/磁盘），用于趋势分析场景。
                         自动排除预测类、阈值类、状态类指标。默认False。
                         当需要查询趋势时，建议设置为true并配合limit=3使用。
    """
    client = get_zabbix_client()

    # 1. 健壮性修复：强制将 search 解析为字典
    if isinstance(search, str):
        try:
            search = json.loads(search)
        except:
            search = {"name": search}

    # 2. 参数标准化
    hostids = parse_list_param(hostids)
    limit_val = parse_int_param(limit) or 20

    # 3. 关键指标模式：智能筛选CPU/内存/磁盘等关键指标
    if key_metrics_only and hostids:
        # 获取该主机的所有活跃监控项（状态正常的）
        all_items = client.item.get(
            hostids=hostids,
            output=["itemid", "name", "key_", "units", "lastvalue", "value_type", "state", "status"],
            filter={"status": "0", "state": "0"},  # 只取已启用且正常的
            limit=500  # 足够覆盖一台主机的所有监控项
        )

        if all_items:
            # 智能评分筛选算法
            scored_items = []

            # 分类评分规则（基于实际API查询结果修正）
            category_rules = {
                # CPU使用率 - 最高优先级
                "cpu": {
                    "keywords": [
                        "system.cpu.intr",              # Linux CPU中断
                        "system.cpu.load",              # Linux CPU负载
                        "perf_counter[\\processor",     # Windows CPU
                        "perf_counter_en[\\processor",  # Windows CPU (英文版)
                        "huawei-server.systemCpuUsage", # 华为物理机
                        "huawei.5300.v5[hwInfoControllerCPUUsage",  # 华为存储
                        # 通用物理机/服务器监控
                        "ipmi.sensor",                  # IPMI 传感器（Dell/HP等）
                        "hardware.cpu.usage",           # 通用硬件CPU
                        "dell.server.cpu",              # Dell 服务器
                        "hp.server.cpu",                # HP 服务器
                        "snmp.cpu"                      # SNMP CPU监控
                    ],
                    "score": 100
                },
                # 内存使用率 - 高优先级
                "memory": {
                    "keywords": [
                        "vm.memory.size[pavailable]",    # Linux 内存百分比（优先）
                        "vm.memory.size[pused]",         # Linux 内存已用百分比
                        "perf_counter[\\memory",         # Windows 内存
                        "perf_counter_en[\\memory",      # Windows 内存 (英文版)
                        "huawei-server.systemMemUsage",  # 华为物理机
                        "huawei.5300.v5[hwInfoControllerMemoryUsage",  # 华为存储
                        # 通用物理机/服务器监控
                        "ipmi.sensor",                   # IPMI 内存（Dell/HP等）
                        "hardware.memory.usage",         # 通用硬件内存
                        "dell.server.memory",            # Dell 服务器
                        "hp.server.memory",              # HP 服务器
                        "snmp.memory"                    # SNMP 内存监控
                    ],
                    "score": 95
                },
                # 磁盘使用率 - 高优先级
                "disk": {
                    "keywords": [
                        "vfs.fs.dependent.size[pused]",   # Linux/Windows 空间使用率
                        "vfs.fs.dependent.inode[pfree]",  # Linux Inode使用率
                        "vfs.fs.dependent.inode[pused]",  # Linux Inode已用
                        "perf_counter[\\logicaldisk",     # Windows 逻辑磁盘
                        "perf_counter_en[\\logicaldisk",  # Windows 逻辑磁盘(英文)
                        "dell.server.hw.physicaldisk",    # Dell 物理磁盘
                        "hardware.disk.usage"             # 通用硬件磁盘
                    ],
                    "score": 95
                },
                # 磁盘IO（次选）
                "disk_io": {
                    "keywords": [
                        "vfs.dev.queue_size",            # Linux 磁盘队列
                        "vfs.dev.read.rate",             # Linux 读速率
                        "vfs.dev.write.rate",            # Linux 写速率
                        "perf_counter[\\physicaldisk",   # Windows 物理磁盘
                        "perf_counter_en[\\physicaldisk" # Windows 物理磁盘(英文)
                    ],
                    "score": 70
                },
                # 网络流量
                "network": {
                    "keywords": [
                        "net.if.in[",                   # 入流量
                        "net.if.out[",                  # 出流量
                        "perf_counter[\\network",       # Windows 网络
                        "perf_counter_en[\\network"     # Windows 网络(英文)
                    ],
                    "score": 65
                }
            }

            # 硬排除关键词（这些指标完全不适合趋势分析）
            exclude_keywords = [
                # 预测类指标（用户自定义）
                "timeleft", "timeleft12", "timeleft.poly", "forecast", "prediction",
                # 阈值类指标（动态计算）
                "dynamic_threshold", "threshold",
                # Inode 指标（非空间使用率，但保留作为备选）
                # "vfs.fs.dependent.inode",  # 注释掉，因为用户环境在用这个
                # 非百分比内存指标（字节数，趋势意义不大）
                "vm.memory.size[available]", "vm.memory.size[total]", "vm.memory.size[used]",
                "vm.memory.size[free]",
                # 系统信息类
                "uptime", "version", "check", "ping", "hostname", "uname",
                "interrupts per second", "intr",  # 中断次数不是使用率
                # 状态类
                "status", "operstate", "readonly", "contents", "cksum",
                "entirestatus", "health",
                # 总计/常量类
                "total", "maxfiles", "maxproc", "num", "packages.get",
                "memory size", "cache bytes"  # Windows内存字节数
            ]

            # 强降权关键词（阈值、动态计算值等非实际指标）
            threshold_keywords = [
                "threshold", "阈值", "预警", "warn", "dynamic", "动态", "预测",
                "forecast", "per_core", "avg1", "avg5", "avg15"  # 这些是负载细分指标
            ]

            # 优先关键词（有这些词加分）
            prefer_keywords = ["pavailable", "pused", "pfree", "utilization", "usage"]

            for item in all_items:
                name_lower = item.get("name", "").lower()
                key_lower = item.get("key_", "").lower()

                # 硬排除：如果匹配排除关键词，直接跳过
                should_exclude = False
                for exclude_kw in exclude_keywords:
                    if exclude_kw.lower() in name_lower or exclude_kw.lower() in key_lower:
                        should_exclude = True
                        break
                if should_exclude:
                    continue

                # 计算分数
                score = 0
                categories = []

                for category, rule in category_rules.items():
                    for kw in rule["keywords"]:
                        kw_lower = kw.lower()
                        if kw_lower in name_lower or kw_lower in key_lower:
                            score += rule["score"]
                            categories.append(category)
                            break  # 每个类别只加一次分

                # 优先关键词加分（有百分比/使用率关键词）
                for prefer_kw in prefer_keywords:
                    if prefer_kw in key_lower or prefer_kw in name_lower:
                        score += 15

                # 强降权：阈值/动态计算类指标（非实际观测值）
                for threshold_kw in threshold_keywords:
                    if threshold_kw in name_lower or threshold_kw in key_lower:
                        score -= 50  # 大幅降权

                # 活跃状态加分（有最新数据的）
                lastvalue = item.get("lastvalue")
                if lastvalue:
                    try:
                        if float(lastvalue) > 0:
                            score += 10
                    except (ValueError, TypeError):
                        # 非数字值（如字符串状态），给予基础活跃分
                        score += 5

                # 数值类型优先（方便趋势分析）
                if item.get("value_type") in ["0", "3"]:  # float或unsigned
                    score += 5

                if score > 0:
                    scored_items.append({
                        "item": item,
                        "score": score,
                        "categories": categories
                    })

            # 按分数排序
            scored_items.sort(key=lambda x: x["score"], reverse=True)

            # 精选策略：严格限制每个核心类别只选一个最佳指标
            selected_items = []
            selected_ids = set()
            # 核心类别映射：主类别 -> 包含的子类别
            category_mapping = {
                "cpu": ["cpu", "cpu_load"],
                "memory": ["memory"],
                "disk": ["disk", "disk_io"]
            }
            covered_main_categories = set()

            # 第一轮：每个核心类别只选一个最高分
            for main_cat, sub_cats in category_mapping.items():
                if len(selected_items) >= 3:  # 严格限制最多3个
                    break
                # 找出属于该类别的所有项目，按分数排序
                cat_items = [s for s in scored_items if any(c in sub_cats for c in s["categories"])]
                if cat_items:
                    # 选该类别分数最高的一个
                    best = cat_items[0]
                    item_id = best["item"]["itemid"]
                    if item_id not in selected_ids:
                        selected_items.append(best["item"])
                        selected_ids.add(item_id)
                        covered_main_categories.add(main_cat)

            # 第二轮：如果还有空位，从其他高分项目填补（但限制总数为3）
            for scored in scored_items:
                if len(selected_items) >= 3:
                    break
                item_id = scored["item"]["itemid"]
                if item_id not in selected_ids:
                    selected_items.append(scored["item"])
                    selected_ids.add(item_id)

            return format_response(selected_items)

    # 4. 语义增强 - 基于实际 Zabbix 环境的通用搜索模式
    # 覆盖 Linux/Windows/物理机(Dell/HP/华为)/存储设备的实际 key 命名
    semantic_map = {
        # 内存相关
        "memory": {
            "keywords": ["memory", "mem", "内存"],
            "key_patterns": [
                "*vm.memory.size[pavailable]*",    # Linux 内存百分比
                "*vm.memory*",                     # Linux 其他内存指标
                "*\\memory\\*",                    # Windows perf_counter
                "*perf_counter*memory*",           # Windows (带_en后缀)
                "*huawei-server.systemMemUsage*",  # 华为物理机
                "*huawei*mem*usage*",              # 华为存储
                "*ipmi*memory*",                   # IPMI 内存（Dell/HP）
                "*hardware*memory*",               # 通用硬件内存
                "*dell*memory*"                    # Dell 服务器
            ]
        },
        # CPU 相关
        "cpu": {
            "keywords": ["cpu", "processor", "处理器"],
            "key_patterns": [
                "*system.cpu.load*",               # Linux CPU 负载
                "*system.cpu.intr*",               # Linux CPU 中断
                "*\\processor*\\*",               # Windows perf_counter
                "*perf_counter*processor*",        # Windows (带_en后缀)
                "*huawei-server.systemCpuUsage*",  # 华为物理机
                "*huawei*cpu*usage*",              # 华为存储
                "*ipmi*cpu*",                      # IPMI CPU（Dell/HP）
                "*hardware*cpu*",                  # 通用硬件CPU
                "*dell*cpu*"                       # Dell 服务器
            ]
        },
        # 磁盘空间使用率
        "disk": {
            "keywords": ["disk", "space", "storage", "磁盘", "空间", "容量"],
            "key_patterns": [
                "*vfs.fs.dependent.size*pused*",   # Linux/Windows 空间使用率
                "*vfs.fs.dependent.inode*pfree*",  # Linux Inode使用率
                "*vfs.fs.dependent.inode*pused*",  # Linux Inode已用
                "*vfs.fs*size*",                   # 通用磁盘大小
                "*\\logicaldisk*\\*",             # Windows LogicalDisk
                "*dell*disk*",                     # Dell 磁盘
                "*hardware*disk*"                  # 通用硬件磁盘
            ]
        },
        # 磁盘IO性能
        "disk_io": {
            "keywords": ["disk io", "io", "read", "write", "磁盘io", "读写"],
            "key_patterns": [
                "*vfs.dev.queue_size*",            # Linux 磁盘队列
                "*vfs.dev.read*",                  # Linux 读指标
                "*vfs.dev.write*",                 # Linux 写指标
                "*vfs.dev*rate*",                  # Linux 速率
                "*\\physicaldisk*\\*",            # Windows PhysicalDisk
                "*perf_counter*physicaldisk*"      # Windows (带_en后缀)
            ]
        },
        # 网络流量
        "network": {
            "keywords": ["network", "net", "traffic", "带宽", "流量", "网络"],
            "key_patterns": [
                "*net.if.in*",                     # 入流量
                "*net.if.out*",                    # 出流量
                "*\\network*\\*",                  # Windows Network
                "*perf_counter*network*"           # Windows (带_en后缀)
            ]
        },
        # 负载
        "load": {
            "keywords": ["load", "负载"],
            "key_patterns": [
                "*system.cpu.load*",
                "*\\system\\*load*"
            ]
        }
    }

    # 搜索关键词分类检测
    def detect_search_category(search_term):
        """检测搜索词属于哪个类别，返回 (category, priority)"""
        term_lower = search_term.lower()

        # 磁盘IO检测（优先于 disk，因为更具体）
        disk_io_indicators = ["io", "i/o", "read", "write", "读写", "性能", "performance", "iops", "latency", "延迟"]
        if any(ind in term_lower for ind in disk_io_indicators):
            return "disk_io", 2  # 高优先级

        # 磁盘空间检测
        disk_space_indicators = ["space", "usage", "used", "free", "空间", "使用", "容量", "storage", "filesystem"]
        if any(ind in term_lower for ind in disk_space_indicators):
            return "disk", 1

        # 其他类别检测
        for category, config in semantic_map.items():
            if category == "disk_io":  # 已处理
                continue
            for kw in config["keywords"]:
                if kw.lower() in term_lower:
                    return category, 1

        return None, 0

    # 智能搜索关键词生成
    def generate_search_patterns(search_term, detected_category):
        """根据检测到的类别生成搜索模式"""
        if detected_category and detected_category in semantic_map:
            config = semantic_map[detected_category]
            # 返回该类别的关键模式
            return config["key_patterns"]

        # 默认：返回原始搜索词的通配符模式
        return [f"*{search_term}*"]

    params = {
        "output": ["itemid", "name", "key_", "units", "lastvalue"],
        "hostids": hostids,
        "limit": limit_val,
        "searchWildcardsEnabled": True,
        "searchByAny": True,
        "sortfield": "name"
    }

    if isinstance(search, dict):
        # 尝试多模式搜索策略
        all_results = []
        seen_itemids = set()

        for k, v in search.items():
            keyword = str(v).lower().strip("*")

            # 检测搜索类别
            category, priority = detect_search_category(keyword)

            if category and category in semantic_map:
                config = semantic_map[category]
                patterns = config["key_patterns"]

                # 策略：尝试多个 key_patterns，合并结果
                for pattern in patterns[:3]:  # 最多试3个模式
                    try:
                        search_params = params.copy()
                        search_params["search"] = {
                            "name": f"*{keyword}*",
                            "key_": pattern
                        }
                        batch = client.item.get(**search_params)

                        # 去重合并
                        for item in batch:
                            if item["itemid"] not in seen_itemids:
                                seen_itemids.add(item["itemid"])
                                all_results.append(item)
                    except Exception as e:
                        logger.debug(f"搜索模式 {pattern} 失败: {e}")
                        continue

                    # 如果找到足够结果，停止尝试
                    if len(all_results) >= limit_val:
                        break

                logger.debug(f"语义搜索 '{keyword}' -> 类别 '{category}', 找到 {len(all_results)} 个结果")

            else:
                # 默认通配符搜索
                try:
                    search_params = params.copy()
                    search_params["search"] = {k: f"*{keyword}*"}
                    if k == "name":
                        search_params["search"]["key_"] = f"*{keyword}*"
                    all_results = client.item.get(**search_params)
                except Exception as e:
                    logger.debug(f"默认搜索失败: {e}")

        result = all_results[:limit_val] if all_results else []

    else:
        # 没有 search 参数时的默认查询
        try:
            result = client.item.get(**params)
        except Exception as e:
            return f"查询出错: {str(e)}"

    # 5. Fallback 逻辑 - 如果语义搜索无结果，尝试推荐相关指标
    if not result and hostids:
        # 根据搜索词智能推荐
        detected_category, _ = detect_search_category(str(search))

        if detected_category == "disk" or detected_category == "disk_io":
            # 推荐磁盘相关指标
            fallback_patterns = ["*vfs.fs*", "*vfs.dev*"]
        elif detected_category == "memory":
            fallback_patterns = ["*vm.memory*"]
        elif detected_category == "cpu":
            fallback_patterns = ["*system.cpu*"]
        elif detected_category == "network":
            fallback_patterns = ["*net.if*"]
        else:
            fallback_patterns = ["*util*", "*usage*"]

        fallback_results = []
        for pattern in fallback_patterns[:2]:  # 最多试2个模式
            try:
                fb = client.item.get(
                    hostids=hostids,
                    output=["name", "key_", "units"],
                    limit=10,
                    search={"key_": pattern},
                    searchByAny=True,
                    searchWildcardsEnabled=True
                )
                fallback_results.extend(fb)
            except:
                continue

        if fallback_results:
            # 去重
            seen_keys = set()
            unique_items = []
            for item in fallback_results:
                key = item.get("key_", "")
                if key not in seen_keys:
                    seen_keys.add(key)
                    unique_items.append(item)

            ref = "\n".join([f"- {i['name']} (Key: {i['key_']}, Units: {i.get('units', '')})"
                            for i in unique_items[:10]])

            hint = f"未找到精确匹配。根据您的搜索，以下是该主机相关的监控项，请尝试使用 `key_metrics_only=true` 获取关键指标：\n{ref}"
            return hint

    if not result:
        return f"未找到匹配项。搜索参数: {search}。请尝试更具体的关键词，或直接使用 `key_metrics_only=true` 获取关键性能指标。"

    return format_response(result)


def trigger_get(
    triggerids: Union[List[str], str, None] = None,
    hostids: Union[List[str], str, None] = None,
    groupids: Union[List[str], str, None] = None,
    templateids: Union[List[str], str, None] = None,
    priority: Union[List[int], int, str, None] = None,
    output: Union[str, List[str], None] = None,
    search: Union[Dict[str, str], str, None] = None,
    filter: Union[Dict[str, Any], str, None] = None,
    limit: Union[int, str, None] = 20,
    include_expression: bool = False
) -> str:
    """获取触发器列表。

    重要提示：
    - 默认返回20条（可通过 limit 调整，建议不超过50）
    - 默认不返回 expression 字段（节省Token），如需请设置 include_expression=true
    - 建议按 priority 筛选（如 priority=3,4,5 只看严重/紧急/灾难级别）

    Args:
        triggerids: 触发器ID列表
        hostids: 主机ID列表
        groupids: 主机组ID列表
        templateids: 模板ID列表
        priority: 严重级别（0=未分类, 1=信息, 2=警告, 3=一般严重, 4=严重, 5=灾难）
        output: 输出字段列表（默认返回核心字段）
        search: 搜索条件（如 {"description": "CPU"}）
        filter: 过滤条件
        limit: 返回数量限制（默认20，建议不超过50以防Token溢出）
        include_expression: 是否返回触发器表达式（默认false，expression很长会占用大量Token）
    """
    client = get_zabbix_client()

    # Parse parameters
    triggerids = parse_list_param(triggerids)
    hostids = parse_list_param(hostids)
    groupids = parse_list_param(groupids)
    templateids = parse_list_param(templateids)
    search = parse_dict_param(search)
    filter = parse_dict_param(filter)
    limit = parse_int_param(limit) or 20

    # Parse priority parameter
    if priority is not None:
        if isinstance(priority, str):
            try:
                parsed = json.loads(priority)
                if isinstance(parsed, list):
                    priority = [int(p) for p in parsed]
                else:
                    priority = int(parsed)
            except (json.JSONDecodeError, ValueError):
                if ',' in priority:
                    priority = [int(p.strip()) for p in priority.split(',')]
                else:
                    priority = int(priority)

    # Default to core fields for better performance, exclude expression to save tokens
    if output is None:
        output = ["triggerid", "description", "priority", "status", "state",
                  "value", "lastchange", "error"]
        if include_expression:
            output.append("expression")

    params = {"output": output, "limit": limit}

    if triggerids:
        params["triggerids"] = triggerids
    if hostids:
        params["hostids"] = hostids
    if groupids:
        params["groupids"] = groupids
    if templateids:
        params["templateids"] = templateids
    if priority is not None:
        params["priority"] = priority
    if search:
        params["search"] = search
    if filter:
        params["filter"] = filter

    result = client.trigger.get(**params)
    return format_response(result)


def event_get(
    eventids: Union[List[str], str, None] = None,
    groupids: Union[List[str], str, None] = None,
    hostids: Union[List[str], str, None] = None,
    objectids: Union[List[str], str, None] = None,
    source: Union[int, str, None] = None,
    object_: Union[int, str, None] = None,
    value: Union[int, str, None] = None,
    severities: Union[List[int], str, None] = None,
    time_from: Union[int, str, None] = None,
    time_till: Union[int, str, None] = None,
    limit: Union[int, str, None] = 10,
    output: Any = None
) -> str:
    """获取事件列表。仅用于查询历史事件记录，不要用于查询当前问题。

    重要区分（必看）：
    - 查【当前未解决问题】→ 用 get_problem_summary（已格式化，直接展示）
    - 查【历史事件/已恢复事件】→ 用 event_get

    参数 value 的含义：
    - value=1：问题发生（当前活跃的问题）
    - value=0：问题已恢复（已解决的历史事件）

    翻页机制说明（重要）：
    当查询时间范围内的事件数量超过 limit 时，需要分批获取避免 Token 溢出。
    由于 Zabbix 按时间倒序返回（最新的在前），翻页是向更早的时间推进：

    1. 首次查询：指定 time_from（如"7d"）和 limit（如50）
       → 返回最新的 50 条记录
       → 查看返回结果开头的"翻页信息"注释

    2. 判断继续：如果"是否还有更多"为"是"，继续翻页

    3. 下一页查询：使用 time_from=第一次的绝对时间戳, time_till=最早记录时间戳-1
       → 必须用绝对时间戳（如 1773660800），不能用相对时间（如"7d"）
       → 因为相对时间每次都会重新计算，导致时间窗口不一致

    翻页示例（查询过去一周的事件）：
        第1次: event_get(hostids="12345", time_from="7d", limit=50)
               → 返回最新的50条，翻页信息提示"还有更多"
               → 记录 time_from 的绝对值: 1773660800
               → 最早记录时间是 1774275680
        第2次: event_get(hostids="12345", time_from=1773660800, time_till=1774275679, limit=50)
               → 使用绝对时间戳翻页，返回更早的50条
        第3次: event_get(hostids="12345", time_from=1773660800, time_till=新时间戳-1, limit=50)
               → 继续用绝对时间戳翻页...

    何时停止翻页（重要）：
    - 当翻页信息中显示"是否还有更多: 否"时，**必须立即停止翻页**
    - 当"返回数量 < limit"时，说明该时间范围内已获取全部数据，停止翻页
    - 当"最早记录时间"已接近"查询范围"起点时，停止翻页

    翻页结束后的处理：
    - 停止调用 event_get
    - 基于已获取的所有事件数据进行分析和总结
    - 生成最终报告或回答用户问题

    适用场景：
    - 追溯某台主机昨天发生了什么事件
    - 查看某个触发器的历史触发记录
    - 统计某段时间内的事件数量

    不适用场景（不要用 event_get）：
    - 查当前有哪些未确认的告警 → 用 get_problem_summary()
    - 查当前整体告警概况 → 用 get_problem_summary()

    Args:
        eventids: 事件ID列表（可选，精确查询特定事件）
        groupids: 主机组ID列表（可选，查询特定主机组的事件）
        hostids: 主机ID列表（可选，查询特定主机的事件）
        objectids: 对象ID（可选，查询特定触发器的事件）
        source: 事件来源（可选，0=触发器, 1=自动发现, 2=自动注册, 3=内部事件）
        object_: 事件对象类型（可选，0=触发器, 1=监控项, 2=LLD规则）
        value: 事件状态过滤（可选，0=问题, 1=恢复）
        severities: 严重级别列表（可选，0-5）
        time_from: 起始时间（可选，Unix时间戳或相对时间如"7d"）
                   翻页时保持 time_from 不变，只调整 time_till 向更早时间推进
        time_till: 截止时间（可选，Unix时间戳或相对时间，默认当前）
                   翻页用法：将上次返回的"最早记录时间戳-1"作为新的 time_till
        limit: 每页返回数量上限（可选，默认10条），建议 20-50 避免 Token 溢出
        output: 返回字段列表（可选）

    Returns:
        JSON格式的事件列表，包含 eventid、name、severity、clock、hosts 等字段

    使用场景（仅用于历史追溯）：
        - 场景1：查询某主机昨天发生了什么事件（已恢复的）
          event_get(hostids="12345", value=0, time_from="24h", limit=20)
        - 场景2：查询特定时间段内的事件
          event_get(time_from="7d", limit=50)
        - 场景3：查询特定触发器的历史触发记录
          event_get(objectids="67890", limit=20)

    错误用法（不要这样做）：
        - 不要用 event_get 查当前问题 → 用 get_problem_summary()
        - 不要传 value=0 查"当前问题" → value=0 表示已恢复
    """
    client = get_zabbix_client()

    # Parse parameters
    eventids = parse_list_param(eventids)
    groupids = parse_list_param(groupids)
    hostids = parse_list_param(hostids)
    objectids = parse_list_param(objectids)
    limit = parse_int_param(limit) or 10
    # 使用 parse_time_param 支持相对时间字符串（如 "24h", "7d"）
    time_from = parse_time_param(time_from, None)
    time_till = parse_time_param(time_till, None)
    source = parse_int_param(source)
    object_val = parse_int_param(object_)
    value_filter = parse_int_param(value)

    # Parse severities for event_get
    if severities is not None:
        if isinstance(severities, str):
            try:
                parsed = json.loads(severities)
                severities = [int(s) for s in parsed] if isinstance(parsed, list) else [int(parsed)]
            except:
                if ',' in severities:
                    severities = [int(s.strip()) for s in severities.split(',')]
                else:
                    severities = [int(severities)]

    # Default output for event_get - include value field for local filtering
    if output is None:
        output = ["eventid", "name", "severity", "clock", "acknowledged", "objectid", "value"]
    elif isinstance(output, list) and "value" not in output:
        output = list(output) + ["value"]

    params = {
        "output": output,
        "limit": limit,
        "sortfield": "clock",
        "sortorder": "DESC",
        "selectHosts": ["hostid", "name"]
    }

    if eventids:
        params["eventids"] = eventids
    if groupids:
        params["groupids"] = groupids
    if hostids:
        params["hostids"] = hostids
    if objectids:
        params["objectids"] = objectids
    if severities is not None:
        params["severities"] = severities
    if source is not None:
        params["source"] = source
    if object_val is not None:
        params["object"] = object_val
    if time_from:
        params["time_from"] = time_from
    if time_till:
        params["time_till"] = time_till

    try:
        result = client.event.get(**params)
        # Local filtering by value since Zabbix 7.0 API doesn't support 'value' as input param
        if value_filter is not None and result:
            result = [item for item in result if int(item.get("value", -1)) == value_filter]

        # 添加翻页元数据，帮助 LLM 判断是否继续查询
        if result and time_from:
            # 获取结果中最小的时间戳（最早的记录）
            min_clock = min(int(item.get("clock", 0)) for item in result)
            time_from_val = time_from  # time_from 已经被 parse_time_param 解析为整数

            # 判断是否还有更多数据：如果返回数量等于limit，说明可能有更多；否则没有更多
            has_more = len(result) >= limit

            # 在结果前添加翻页提示（作为注释，不影响 JSON 解析）
            if has_more:
                pagination_info = f"""/* 翻页信息（不要展示给用户）：
- 本次返回: {len(result)} 条记录 (limit={limit})
- 最早记录时间: {min_clock} ({datetime.fromtimestamp(min_clock).strftime('%Y-%m-%d %H:%M:%S')})
- 查询范围: {time_from_val} ({datetime.fromtimestamp(time_from_val).strftime('%Y-%m-%d %H:%M:%S')}) 到 {time_till or '现在'}
- 是否还有更多: 是
- 如需继续翻页: 使用 time_from={time_from_val}, time_till={min_clock - 1} 查询下一页
  （注意：翻页时必须用绝对时间戳，不能用相对时间如"24h"）
*/

"""
            else:
                pagination_info = f"""/* 翻页信息（不要展示给用户）：
- 本次返回: {len(result)} 条记录 (limit={limit})
- 最早记录时间: {min_clock} ({datetime.fromtimestamp(min_clock).strftime('%Y-%m-%d %H:%M:%S')})
- 查询范围: {time_from_val} ({datetime.fromtimestamp(time_from_val).strftime('%Y-%m-%d %H:%M:%S')}) 到 {time_till or '现在'}
- 是否还有更多: 否（返回数量少于limit，已获取全部数据）
- 【重要】请停止翻页，直接基于已获取的 {len(result)} 条记录进行分析和总结
*/

"""
            return pagination_info + format_response(result)

        return format_response(result)
    except Exception as e:
        return f"查询失败: {str(e)}"


def history_get(
    itemids: Union[List[str], str],
    history: Union[int, str] = 0,
    time_from: Union[int, str, None] = None,
    time_till: Union[int, str, None] = None,
    limit: Union[int, str, None] = None,
    sortfield: str = "clock",
    sortorder: str = "DESC"
) -> str:
    """获取监控项历史数据（原始采集值）。

    详细说明：返回监控项的原始历史数据，即每次采集的具体数值。

    与 trend_get 的区别（重要）：
    - history_get：返回原始采集数据，数据量大，适合查看具体时间点数值或精细分析
    - trend_get：返回每小时聚合数据（最大/最小/平均值），数据量小，适合长期趋势分析

    选择建议：
    - 查看最近几小时的详细数据 → 使用 history_get
    - 查看几天或几周的趋势 → 使用 trend_get
    - 只需要统计摘要 → 使用 trend_summary

    Args:
        itemids: 监控项ID（必选），可通过 item_get 查询获取
        history: 数据类型（可选，默认0）
                0=float浮点数, 1=character字符, 2=log日志,
                3=unsigned无符号整数, 4=text文本
        time_from: 起始时间（可选），支持两种格式：
                   - 相对时间字符串："1h"=1小时前, "24h"=24小时前, "7d"=7天前
                   - Unix时间戳（如 1773990849）
                   💡 强烈推荐使用相对时间字符串，系统自动计算
        time_till: 截止时间（可选），格式同 time_from，不传默认为当前时间
        limit: 返回条数限制（可选，默认10条）
        sortfield: 排序字段（可选，默认 "clock" 按时间排序）
        sortorder: 排序方向（可选，"ASC" 升序 或 "DESC" 降序，默认降序）

    Returns:
        JSON格式的历史数据列表，每条记录包含：
        - clock: Unix时间戳（秒）
        - value: 采集值
        - ns: 纳秒部分（用于精确时间）

    使用场景：
        - 场景1：查询最近1小时的详细数据（推荐）
          history_get(itemids="424943", history=0, time_from="1h", limit=100)
        - 场景2：查询最近24小时的数据
          history_get(itemids="424943", history=0, time_from="24h", limit=100)
        - 场景3：查询最近7天的大量数据
          history_get(itemids="424943", history=0, time_from="7d", limit=1000)
        - 场景4：查询特定时间范围（只有这时才用时间戳）
          history_get(itemids="424943", time_from=1772284800, time_till=1772371199)
    """
    # Parse parameters
    itemids = parse_list_param(itemids)
    history = parse_int_param(history)
    limit = parse_int_param(limit, 10)
    # 使用 parse_time_param 支持相对时间（如 "1h", "24h"）
    from utils.params import parse_time_param
    import time
    time_from = parse_time_param(time_from, 0) if time_from else None
    time_till = parse_time_param(time_till, 0) if time_till else None

    # 时间戳合理性检查：如果 time_from 是过去超过7天的时间戳，提示使用相对时间
    current_time = int(time.time())
    if time_from and (current_time - time_from) > (7 * 24 * 3600):
        return "错误：time_from 时间戳太老（超过7天前），可能是手动计算错误。\n" \
               "请使用相对时间格式：time_from='2h'（最近2小时）、time_from='24h'（最近24小时）、time_from='7d'（最近7天）\n" \
               "系统会自动计算正确的时间戳。"

    client = get_zabbix_client()
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
    return format_response(result)
