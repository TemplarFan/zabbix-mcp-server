"""Query Tools - MCP tools for basic data queries."""
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Annotated, Any, Dict, List, Optional, Union

from pydantic import Field

from client import get_zabbix_client
from utils.params import parse_int_param, parse_list_param, parse_dict_param, parse_time_param
from utils.format import format_response

logger = logging.getLogger(__name__)

# 定义北京时区 (UTC+8)
BEIJING_TZ = timezone(timedelta(hours=8))
EVENT_QUERY_PAGE_SIZE = 1000


def _format_events_as_table(events: list) -> str:
    """Format events list as markdown table for better display."""
    if not events:
        return "暂无事件数据"

    lines = ["| 时间 | 主机 | 问题 | 级别 |", "|------|------|------|------|"]

    severity_names = {"0": "未分类", "1": "信息", "2": "警告", "3": "一般", "4": "严重", "5": "灾难"}

    for event in events:
        clock = event.get("clock", 0)
        try:
            time_str = datetime.fromtimestamp(int(clock), tz=BEIJING_TZ).strftime("%m-%d %H:%M")
        except (TypeError, ValueError, OSError, OverflowError):
            time_str = str(clock)

        hosts = event.get("hosts", [{}])
        host_name = hosts[0].get("name", "Unknown") if hosts else "Unknown"

        name = event.get("name", "Unknown")
        severity = str(event.get("severity", "0"))
        sev_name = severity_names.get(severity, severity)

        lines.append(f"| {time_str} | {host_name} | {name} | {sev_name} |")

    return "\n".join(lines)


def host_get(
    hostids: Annotated[Union[List[Any], str, int, None], Field(description="主机ID（单个或逗号分隔多个）")] = None,
    name: Annotated[Optional[str], Field(description="主机名关键词，模糊匹配")] = None,
    groupids: Annotated[Union[List[Any], str, int, None], Field(description="主机组ID筛选")] = None,
    templateids: Annotated[Union[List[Any], str, int, None], Field(description="模板ID筛选")] = None,
    output: Annotated[Union[str, List[str], None], Field(description="返回字段列表")] = None,
    search: Annotated[Union[Dict[str, str], str, None], Field(description="搜索条件字典")] = None,
    filter: Annotated[Union[Dict[str, Any], str, None], Field(description="精确过滤条件")] = None,
    selectGroups: Annotated[bool, Field(description="是否返回主机所属群组信息")] = False,
    selectInventory: Annotated[bool, Field(description="是否返回主机资产信息")] = False,
    limit: Annotated[Union[int, str, None], Field(description="返回数量（默认10）")] = 10
) -> str:
    """查询主机列表。支持ID精确查询或名称模糊匹配，已知IP时优先用get_host_by_ip"""
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
    if selectGroups:
        params["selectGroups"] = ["groupid", "name"]
    if selectInventory:
        params["selectInventory"] = [
            "software", "software_full",
            "software_app_a", "software_app_b", "software_app_c",
            "software_app_d", "software_app_e"
        ]

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
    itemids: Annotated[Union[List[Any], str, int, None], Field(description="监控项ID")] = None,
    hostids: Annotated[Union[List[Any], str, int, None], Field(description="主机ID")] = None,
    search: Annotated[Union[Dict[str, str], str, None], Field(description="搜索关键词或条件字典（支持语义搜索如memory/cpu）")] = None,
    limit: Annotated[Union[int, str, None], Field(description="返回数量（默认20）")] = None,
    output: Annotated[Any, Field(description="返回字段列表")] = None,
    key_metrics_only: Annotated[bool, Field(description="仅返回关键性能指标（CPU/内存/磁盘），每类最多1个")] = False
) -> str:
    """查询监控项。需先通过host_get获取hostid。支持语义搜索，key_metrics_only智能筛选最佳指标"""
    client = get_zabbix_client()

    # 1. 健壮性修复：强制将 search 解析为字典
    if isinstance(search, str):
        try:
            search = json.loads(search)
        except ValueError:
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
            except Exception as exc:
                logging.warning("item.get 回退查询模式 %s 失败: %s", pattern, exc)
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
    triggerids: Annotated[Union[List[Any], str, int, None], Field(description="触发器ID")] = None,
    hostids: Annotated[Union[List[Any], str, int, None], Field(description="主机ID筛选")] = None,
    groupids: Annotated[Union[List[Any], str, int, None], Field(description="群组ID筛选")] = None,
    templateids: Annotated[Union[List[Any], str, int, None], Field(description="模板ID筛选")] = None,
    priority: Annotated[Union[List[int], int, str, None], Field(description="严重级别（0未分类/1信息/2警告/3一般/4严重/5灾难）")] = None,
    output: Annotated[Union[str, List[str], None], Field(description="返回字段列表")] = None,
    search: Annotated[Union[Dict[str, str], str, None], Field(description="搜索条件")] = None,
    filter: Annotated[Union[Dict[str, Any], str, None], Field(description="精确过滤条件")] = None,
    limit: Annotated[Union[int, str, None], Field(description="返回数量（默认20）")] = 20,
    include_expression: Annotated[bool, Field(description="是否返回触发表达式（默认False节省Token）")] = False
) -> str:
    """查询触发器列表。priority=3,4,5只看严重以上级别"""
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


def _parse_event_time_parameter(name: str, value: Any) -> Optional[int]:
    if value is None:
        return None
    parsed = parse_time_param(value, None)
    if parsed is None:
        raise ValueError(f"{name} 格式无效")
    return parsed


def _event_pagination_header(
    scanned: int,
    returned: int,
    has_more: bool,
    next_cursor: Optional[str],
) -> str:
    return "\n".join([
        "/* 翻页信息（不要展示给用户）：",
        f"- 候选扫描: {scanned}",
        f"- 实际返回: {returned}",
        f"- 是否还有更多: {'是' if has_more else '否'}",
        f"- 下一事件ID游标: {next_cursor or '无'}",
        (
            f"- 如需继续翻页: 使用 eventid_till={next_cursor}，原时间范围参数保持不变"
            if next_cursor
            else "- 已确认当前候选范围扫描完成"
        ),
        "*/",
        "",
    ])


def event_get(
    eventids: Annotated[Union[List[Any], str, int, None], Field(description="事件ID")] = None,
    groupids: Annotated[Union[List[Any], str, int, None], Field(description="群组ID筛选")] = None,
    hostids: Annotated[Union[List[Any], str, int, None], Field(description="主机ID")] = None,
    objectids: Annotated[Union[List[Any], str, int, None], Field(description="触发器ID")] = None,
    source: Annotated[Union[int, str, None], Field(description="事件来源（默认0触发器事件）")] = None,
    object_: Annotated[Union[int, str, None], Field(description="事件对象类型")] = None,
    value: Annotated[Union[int, str, None], Field(description="本地筛选事件状态（1问题发生/0恢复）")] = None,
    severities: Annotated[Union[List[int], str, None], Field(description="严重级别列表")] = None,
    time_from: Annotated[Union[int, str, None], Field(description="起始时间（支持7d/24h或Unix时间戳）")] = None,
    time_till: Annotated[Union[int, str, None], Field(description="截止时间（支持相对时间或Unix时间戳）")] = None,
    eventid_till: Annotated[Union[int, str, None], Field(description="下一页事件ID游标；首次查询不传")] = None,
    limit: Annotated[Union[int, str, None], Field(description="最终返回数量（默认10，不是候选扫描上限）")] = 10,
    output: Annotated[Any, Field(description="返回字段列表")] = None,
) -> str:
    """查询原始历史事件；业务状态解释使用问题事实明细工具。"""
    parsed_limit = parse_int_param(limit)
    if parsed_limit is None or parsed_limit <= 0:
        return "参数错误: limit 必须是正整数"

    value_filter = parse_int_param(value) if value is not None else None
    if value is not None and value_filter not in {0, 1}:
        return "参数错误: value 仅支持 0 或 1"

    cursor: Optional[str] = None
    if eventid_till is not None:
        cursor = str(eventid_till).strip()
        if not cursor.isdigit() or int(cursor) <= 0:
            return "参数错误: eventid_till 必须是正整数"

    try:
        parsed_time_from = _parse_event_time_parameter("time_from", time_from)
        parsed_time_till = _parse_event_time_parameter("time_till", time_till)
    except ValueError as exc:
        return f"参数错误: {exc}"
    if (
        parsed_time_from is not None
        and parsed_time_till is not None
        and parsed_time_from > parsed_time_till
    ):
        return "参数错误: time_from 不能晚于 time_till"

    parsed_source = parse_int_param(source) if source is not None else 0
    if source is not None and parsed_source is None:
        return "参数错误: source 必须是整数"
    parsed_object = parse_int_param(object_) if object_ is not None else None
    if object_ is not None and parsed_object is None:
        return "参数错误: object_ 必须是整数"

    try:
        parsed_severities: Optional[List[int]] = None
        if severities is not None:
            if isinstance(severities, list):
                parsed_severities = [int(item) for item in severities]
            elif isinstance(severities, str):
                try:
                    raw = json.loads(severities)
                except json.JSONDecodeError:
                    raw = [item.strip() for item in severities.split(",")]
                parsed_severities = [int(item) for item in (raw if isinstance(raw, list) else [raw])]
            else:
                parsed_severities = [int(severities)]
    except (TypeError, ValueError):
        return "参数错误: severities 必须是整数列表"

    parsed_eventids = parse_list_param(eventids)
    parsed_groupids = parse_list_param(groupids)
    parsed_hostids = parse_list_param(hostids)
    parsed_objectids = parse_list_param(objectids)

    if output is None:
        output = ["eventid", "name", "severity", "clock", "acknowledged", "objectid", "value", "r_eventid"]
    elif isinstance(output, str) and output != "extend":
        try:
            parsed_output = json.loads(output)
        except json.JSONDecodeError:
            parsed_output = [output]
        output = parsed_output if isinstance(parsed_output, list) else [str(parsed_output)]
    if isinstance(output, list):
        output = list(output)
        for required in ("eventid", "value"):
            if required not in output:
                output.append(required)

    base_params: Dict[str, Any] = {
        "output": output,
        "sortfield": "eventid",
        "sortorder": "DESC",
        "selectHosts": ["hostid", "name"],
    }
    for key, parsed in (
        ("eventids", parsed_eventids),
        ("groupids", parsed_groupids),
        ("hostids", parsed_hostids),
        ("objectids", parsed_objectids),
        ("severities", parsed_severities),
        ("source", parsed_source),
        ("object", parsed_object),
        ("time_from", parsed_time_from),
        ("time_till", parsed_time_till),
    ):
        if parsed is not None:
            base_params[key] = parsed

    client = get_zabbix_client()
    returned_rows: List[Dict[str, Any]] = []
    seen: set[str] = set()
    scanned = 0
    has_more = False
    next_cursor: Optional[str] = None

    try:
        while len(returned_rows) < parsed_limit:
            params = {**base_params, "limit": EVENT_QUERY_PAGE_SIZE}
            if cursor is not None:
                params["eventid_till"] = cursor
            page = client.event.get(**params)
            if not page:
                break

            page_ids: List[int] = []
            stopped_early = False
            for index, item in enumerate(page):
                item_eventid = str(item.get("eventid", ""))
                if not item_eventid.isdigit():
                    raise RuntimeError("Zabbix API 返回了无效的 eventid")
                numeric_eventid = int(item_eventid)
                if numeric_eventid <= 0:
                    raise RuntimeError("Zabbix API 返回了无效的 eventid")
                page_ids.append(numeric_eventid)
                if item_eventid in seen:
                    continue
                seen.add(item_eventid)
                scanned += 1

                if value_filter is None or parse_int_param(item.get("value"), -1) == value_filter:
                    returned_rows.append(item)
                if len(returned_rows) >= parsed_limit:
                    has_more = index < len(page) - 1 or len(page) >= EVENT_QUERY_PAGE_SIZE
                    if has_more and numeric_eventid > 0:
                        next_cursor = str(numeric_eventid - 1)
                    stopped_early = True
                    break

            if stopped_early:
                break
            if len(page) < EVENT_QUERY_PAGE_SIZE:
                break
            if not page_ids:
                raise RuntimeError("Zabbix API 分页页缺少有效 eventid")
            new_cursor = min(page_ids) - 1
            if new_cursor < 0 or (cursor is not None and new_cursor >= int(cursor)):
                raise RuntimeError("Zabbix API 分页游标未前进")
            cursor = str(new_cursor)
    except Exception as exc:
        return f"查询失败: {exc}"

    prefix = _event_pagination_header(
        scanned,
        len(returned_rows),
        has_more,
        next_cursor,
    )
    if scanned == 0:
        prefix += "查询结果为空：范围内没有候选事件。\n\n"
    elif not returned_rows:
        prefix += f"查询结果为空：候选事件中没有符合 value={value_filter} 的记录。\n\n"
    return prefix + format_response(returned_rows)


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


def hostgroup_get(
    name: Annotated[Optional[str], Field(description="群组名称关键词（模糊搜索）")] = None,
    limit: Annotated[Union[int, str, None], Field(description="返回数量（默认50）")] = 50
) -> str:
    """查询主机群组列表"""
    client = get_zabbix_client()
    limit = parse_int_param(limit, 50)

    params = {
        "output": ["groupid", "name"],
        "limit": limit,
        "sortfield": "name",
        "sortorder": "ASC"
    }

    if name:
        params["search"] = {"name": f"*{name}*"}
        params["searchWildcardsEnabled"] = True

    result = client.hostgroup.get(**params)

    if not result:
        return f"未找到匹配的群组。搜索关键词: {name or '无'}"

    return format_response(result)


def hostgroup_get_hosts(
    groupids: Annotated[Union[List[Any], str, int], Field(description="群组ID（单个或逗号分隔多个）")],
    limit: Annotated[Union[int, str, None], Field(description="返回数量（默认50）")] = 50
) -> str:
    """查询群组内的主机列表。需先通过hostgroup_get获取groupid"""
    client = get_zabbix_client()
    groupids = parse_list_param(groupids)
    limit = parse_int_param(limit, 50)

    result = client.host.get(
        groupids=groupids,
        output=["hostid", "host", "name", "status"],
        limit=limit,
        sortfield="name",
        sortorder="ASC"
    )

    if not result:
        return f"群组 {groupids} 下无主机"

    # 统计信息
    total = len(result)
    enabled = sum(1 for h in result if h.get("status") == "0")
    disabled = total - enabled

    summary = f"群组 {groupids} 下共 {total} 台主机（启用: {enabled}, 禁用: {disabled})\n\n"
    return summary + format_response(result)


def host_software_inventory_get(
    host_identifier: Annotated[str, Field(description="主机标识（hostid/IP地址/主机名）")]
) -> str:
    """查询单台主机的软件资产信息（software/software_full/software_app_a-e）"""
    client = get_zabbix_client()

    # 软件相关字段
    software_fields = [
        "software",        # 软件
        "software_full",   # 软件详情
        "software_app_a",  # 软件应用A
        "software_app_b",  # 软件应用B
        "software_app_c",  # 软件应用C
        "software_app_d",  # 软件应用D
        "software_app_e"   # 软件应用E
    ]

    # 字段中文映射
    field_names = {
        "software": "软件",
        "software_full": "软件详情",
        "software_app_a": "软件应用A",
        "software_app_b": "软件应用B",
        "software_app_c": "软件应用C",
        "software_app_d": "软件应用D",
        "software_app_e": "软件应用E"
    }

    # 识别主机标识类型并查询
    host = None

    # 1. 尝试作为 hostid（纯数字）
    if host_identifier.isdigit():
        result = client.host.get(
            hostids=[host_identifier],
            output=["hostid", "host", "name"],
            selectInventory=software_fields
        )
        if result:
            host = result[0]

    # 2. 尝试作为 IP 地址查询
    if not host:
        try:
            interfaces = client.hostinterface.get(
                output=["hostid", "ip"],
                filter={"ip": host_identifier}
            )
            if interfaces:
                hostid = interfaces[0]["hostid"]
                result = client.host.get(
                    hostids=[hostid],
                    output=["hostid", "host", "name"],
                    selectInventory=software_fields
                )
                if result:
                    host = result[0]
        except Exception as exc:
            logging.warning("host.get 按 hostid=%s 查询失败: %s", hostid, exc)

    # 3. 尝试作为主机名精确匹配
    if not host:
        result = client.host.get(
            output=["hostid", "host", "name"],
            selectInventory=software_fields,
            filter={"name": host_identifier}
        )
        if result:
            host = result[0]

    # 4. 尝试作为主机名模糊匹配
    if not host:
        result = client.host.get(
            output=["hostid", "host", "name"],
            selectInventory=software_fields,
            search={"name": f"*{host_identifier}*"},
            searchWildcardsEnabled=True,
            limit=1
        )
        if result:
            host = result[0]

    if not host:
        return f"未找到主机：{host_identifier}"

    # 提取信息
    hostid = host.get("hostid", "")
    host_name = host.get("name", "")
    host_ip = host.get("host", "")
    inventory = host.get("inventory", {})

    # 格式化输出
    lines = []
    lines.append(f"### 主机软件资产信息")
    lines.append(f"")
    lines.append(f"**主机ID**: {hostid}")
    lines.append(f"**主机名**: {host_name}")
    lines.append(f"**IP地址**: {host_ip}")
    lines.append(f"")

    # 检查是否有软件信息
    has_software = any(inventory.get(field) for field in software_fields)

    if not has_software:
        lines.append("该主机未填写软件资产信息")
        return "\n".join(lines)

    # 输出软件信息列表
    lines.append("| 字段 | 内容 |")
    lines.append("|------|------|")

    for field in software_fields:
        value = inventory.get(field, "")
        if value:
            lines.append(f"| {field_names[field]} | {value} |")

    return "\n".join(lines)
