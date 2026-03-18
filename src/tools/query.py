"""Query Tools - MCP tools for basic data queries."""
import json
import logging
from typing import Any, Dict, List, Optional, Union

from client import get_zabbix_client
from utils.params import parse_int_param, parse_list_param, parse_dict_param
from utils.format import format_response

logger = logging.getLogger(__name__)


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
    """获取主机信息。支持通过ID精确查询或通过名称模糊查询。

    Args:
        hostids: 主机ID列表。
        name: 主机名关键词，支持模糊匹配（如输入"情报"可搜出"情报系统应用服务器"）。
        groupids: 主机组ID过滤。
        output: 返回字段，默认为核心字段。
        limit: 最大返回数量，默认10条，防止数据过载。
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
            return f"未找到匹配项。搜索关键词: {name if name else '无'}"

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

    Args:
        itemids: 监控项ID列表
        hostids: 主机ID列表
        search: 搜索条件（如 {"name": "cpu"}）
        limit: 返回数量限制
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
    limit: Union[int, str, None] = None
) -> str:
    """Get triggers from Zabbix with optional filtering."""
    client = get_zabbix_client()

    # Parse parameters
    triggerids = parse_list_param(triggerids)
    hostids = parse_list_param(hostids)
    groupids = parse_list_param(groupids)
    templateids = parse_list_param(templateids)
    search = parse_dict_param(search)
    filter = parse_dict_param(filter)
    limit = parse_int_param(limit)

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

    # Default to core fields for better performance
    if output is None:
        output = ["triggerid", "description", "priority", "status", "state",
                  "value", "lastchange", "error", "expression"]

    params = {"output": output}

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
    if limit:
        params["limit"] = limit

    result = client.trigger.get(**params)
    return format_response(result)


def problem_get(
    eventids: Union[List[str], str, None] = None,
    groupids: Union[List[str], str, None] = None,
    hostids: Union[List[str], str, None] = None,
    objectids: Union[List[str], str, None] = None,
    acknowledged: Optional[bool] = None,
    severities: Union[List[int], str, None] = None,
    time_from: Union[int, str, None] = None,
    time_till: Union[int, str, None] = None,
    recent: Optional[bool] = None,
    limit: Union[int, str, None] = None,
    output: Any = None
) -> str:
    """Get current problems (active alerts) from Zabbix.

    Note: Zabbix 7.0 problem.get only supports sortfield='eventid'
    """
    client = get_zabbix_client()

    # Parse parameters
    eventids = parse_list_param(eventids)
    groupids = parse_list_param(groupids)
    hostids = parse_list_param(hostids)
    objectids = parse_list_param(objectids)
    limit = parse_int_param(limit) or 20
    time_from = parse_int_param(time_from)
    time_till = parse_int_param(time_till)

    # Parse severities
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

    # Default output
    if output is None:
        output = ["eventid", "name", "severity", "clock", "acknowledged", "objectid"]

    params = {
        "output": output,
        "limit": limit,
        "sortfield": "eventid",
        "sortorder": "DESC"
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
    if acknowledged is not None:
        params["acknowledged"] = acknowledged
    if recent is not None:
        params["recent"] = recent
    if time_from:
        params["time_from"] = time_from
    if time_till:
        params["time_till"] = time_till

    try:
        result = client.problem.get(**params)
        return format_response(result)
    except Exception as e:
        return f"查询失败: {str(e)}"


def event_get(
    eventids: Union[List[str], str, None] = None,
    groupids: Union[List[str], str, None] = None,
    hostids: Union[List[str], str, None] = None,
    objectids: Union[List[str], str, None] = None,
    source: Optional[int] = None,
    object: Optional[int] = None,
    valued: Optional[int] = None,
    severities: Union[List[int], str, None] = None,
    time_from: Union[int, str, None] = None,
    time_till: Union[int, str, None] = None,
    limit: Union[int, str, None] = None,
    output: Any = None
) -> str:
    """Get events from Zabbix with optional filtering."""
    client = get_zabbix_client()

    # Parse parameters
    eventids = parse_list_param(eventids)
    groupids = parse_list_param(groupids)
    hostids = parse_list_param(hostids)
    objectids = parse_list_param(objectids)
    limit = parse_int_param(limit) or 20
    time_from = parse_int_param(time_from)
    time_till = parse_int_param(time_till)

    # Parse severities
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

    # Default output
    if output is None:
        output = ["eventid", "name", "severity", "clock", "acknowledged", "objectid"]

    params = {
        "output": output,
        "limit": limit,
        "sortfield": "eventid",
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
    if object is not None:
        params["object"] = object
    if valued is not None:
        params["valued"] = valued
    if time_from:
        params["time_from"] = time_from
    if time_till:
        params["time_till"] = time_till

    try:
        result = client.event.get(**params)
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
    """Get history data from Zabbix.

    Args:
        itemids: List of item IDs to get history for
        history: History type (0=float, 1=character, 2=log, 3=unsigned, 4=text)
        time_from: Start time (Unix timestamp)
        time_till: End time (Unix timestamp)
        limit: Maximum number of results
        sortfield: Field to sort by
        sortorder: Sort order (ASC or DESC)

    Returns:
        str: JSON formatted history data
    """
    # Parse parameters
    itemids = parse_list_param(itemids)
    history = parse_int_param(history)
    limit = parse_int_param(limit, 10)
    time_from = parse_int_param(time_from)
    time_till = parse_int_param(time_till)

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
