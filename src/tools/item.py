"""监控项查询工具：精确模式、语义搜索、关键指标筛选与空结果证据头。"""
import json
import logging
from typing import Annotated, Any, Dict, List, Union

from pydantic import Field

from client import get_zabbix_client
from ._key_metrics import select_key_metrics
from utils.format import format_response
from utils.params import parse_int_param, parse_list_param

logger = logging.getLogger(__name__)


def _item_get_impl(client, itemids=None, hostids=None, search=None, limit=None, output=None, key_metrics_only=False):
    """查询监控项。需先通过host_get获取hostid。支持语义搜索，key_metrics_only智能筛选最佳指标"""

    # 1. 健壮性修复：强制将 search 解析为字典
    if isinstance(search, str):
        try:
            search = json.loads(search)
        except ValueError:
            search = {"name": search}

    # 2. 参数标准化
    hostids = parse_list_param(hostids)
    limit_val = parse_int_param(limit) or 20

    # 2.5 精确模式：显式 itemid 列表直达 API，不走语义搜索
    itemid_list = parse_list_param(itemids)
    if itemid_list:
        requested_output = output
        if isinstance(requested_output, str):
            try:
                requested_output = json.loads(requested_output)
            except ValueError:
                requested_output = [requested_output]
        result = client.item.get(
            itemids=itemid_list,
            output=requested_output or ["itemid", "name", "key_", "units", "lastvalue"],
            limit=limit_val,
        )
        return format_response(result)

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
            grouped = select_key_metrics(all_items)
            selected: List[Dict[str, Any]] = []
            seen_ids = set()

            # 每个核心类别先取最佳，再从磁盘多分区/其余类别按分补足至 3 个
            for category in ("cpu", "memory", "disk", "disk_io", "network"):
                for entry in grouped.get(category, []):
                    if entry.item["itemid"] not in seen_ids:
                        selected.append(entry.item)
                        seen_ids.add(entry.item["itemid"])
                    break
            for category in ("disk", "disk_io", "network", "cpu", "memory"):
                for entry in grouped.get(category, []):
                    if len(selected) >= 3:
                        break
                    if entry.item["itemid"] not in seen_ids:
                        selected.append(entry.item)
                        seen_ids.add(entry.item["itemid"])
            return format_response(selected[:3])

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
        host_total_line = ""
        if hostids:
            try:
                host_total = client.item.get(hostids=hostids, countOutput=True)
                host_total_line = f"- 该主机监控项总数: {host_total}\n"
            except Exception as exc:
                logging.warning("统计主机监控项总数失败: %s", exc)
        header = (
            "/* 空结果证据（不要展示给用户）：\n"
            f"- 已尝试: 名称/关键字搜索（search={search}）\n"
            + host_total_line +
            "- 总数较大而 0 命中，多为搜索词与英文监控项名不匹配\n"
            "- 建议: 换英文关键词重试；或 trigger_get（默认带关联监控项）经触发器定位；"
            "或用已知同类 key_ 前缀搜索取相关监控项\n"
            "*/\n\n"
        )
        return header + format_response(result)

    return format_response(result)


def item_get(
    itemids: Annotated[Union[List[Any], str, int, None], Field(description="监控项ID")] = None,
    hostids: Annotated[Union[List[Any], str, int, None], Field(description="主机ID")] = None,
    search: Annotated[Union[Dict[str, str], str, None], Field(description="搜索关键词或条件字典（支持语义搜索如memory/cpu）")] = None,
    limit: Annotated[Union[int, str, None], Field(description="返回数量（默认20）")] = None,
    output: Annotated[Any, Field(description="返回字段列表")] = None,
    key_metrics_only: Annotated[bool, Field(description="仅返回关键性能指标（CPU/内存/磁盘），每类最多1个")] = False
) -> str:
    """查询监控项。需先通过host_get获取hostid。支持语义搜索，key_metrics_only智能筛选最佳指标"""
    return _item_get_impl(get_zabbix_client(), itemids, hostids, search, limit, output, key_metrics_only)
