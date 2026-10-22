"""关键指标筛选：按类别关键词为监控项评分并选出各类别最佳指标。

item_get(key_metrics_only) 与 check_host_health 共用本模块，
保证两个工具对同一主机选出一致的关键指标；关键词表覆盖
Linux/Windows/华为（iBMC、OceanStor、5300 V5）/Dell/HP/IPMI/SNMP
与国产服务器的实际 key 命名。评分与选择规则只在此维护一份。
"""

from __future__ import annotations

from typing import Any, Dict, List, NamedTuple


class ScoredItem(NamedTuple):
    """一个被评分的监控项：原始行 + 类别与得分（不修改原始行）。"""

    category: str
    score: int
    item: Dict[str, Any]


CATEGORY_LABELS = {
    "cpu": "CPU使用率",
    "memory": "内存使用率",
    "disk": "磁盘使用率",
    "disk_io": "磁盘IO",
    "network": "网络流量",
}

# 类别评分规则：命中任一关键词即归入该类别并获得基础分。
_CATEGORY_RULES: Dict[str, Dict[str, Any]] = {
    "cpu": {
        "keywords": [
            # Linux 标准
            "system.cpu.util",
            "system.cpu.load",
            # Windows perf_counter
            "perf_counter[\\processor", "perf_counter_en[\\processor",
            "processor information(_total)",
            # 华为 iBMC / OceanStor / 5300 V5 存储
            "systemCpuUsage", "huawei.oceanstor.v6.controller.cpu",
            "huawei.5300.v5[hwInfoControllerCPUUsage", "huawei-server.systemCpuUsage",
            # Dell / HP
            "dell.server.cpu", "dell.server.system.get", "dell.server.hw.diskarray",
            "hp.server.cpu",
            # 华鲲/浪潮等国产服务器
            "cpuAvailability", "cpuStatus[", "cpuCoreCount",
            # 通用硬件监控
            "hardware.cpu.usage", "ipmi.sensor", "snmp.cpu",
        ],
        "score": 100,
    },
    "memory": {
        "keywords": [
            # Linux 使用率（优先）
            "vm.memory.size[pused]",
            "vm.memory.utilization", "vm.memory.util",
            # Windows perf_counter
            "perf_counter[\\memory", "perf_counter_en[\\memory",
            # 华为 iBMC / OceanStor / 5300 V5 存储
            "systemMemUsage", "huawei.oceanstor.v6.controller.memory",
            "huawei.5300.v5[hwInfoControllerMemoryUsage", "huawei-server.systemMemUsage",
            # 国产服务器 / 通用硬件
            "memoryStatus[", "memoryEntireStatus",
            "hardware.memory.usage", "ipmi.sensor", "snmp.memory",
        ],
        "score": 95,
    },
    "disk": {
        "keywords": [
            # Linux 空间使用率（优先）与 inode（备选，评分阶段降权）
            "vfs.fs.dependent.size[",
            "vfs.fs.dependent.inode[",
            # Windows 逻辑/物理磁盘
            "perf_counter[\\logicaldisk", "perf_counter_en[\\logicaldisk",
            "perf_counter[\\physicaldisk", "perf_counter_en[\\physicaldisk",
            # 华为存储容量与 LUN
            "huawei.oceanstor.v6.capacity.used",
            # Dell 物理磁盘 / 国产服务器
            "dell.server.hw.physicaldisk",
            "hardDiskStatus[", "hardDiskEntireStatus", "diskPartitionUsage",
            # 通用硬件
            "hardware.disk.usage",
        ],
        "score": 95,
    },
    "disk_io": {
        "keywords": [
            "vfs.dev.queue_size", "vfs.dev.read.rate", "vfs.dev.write.rate",
        ],
        "score": 70,
    },
    "network": {
        "keywords": [
            "net.if.in[", "net.if.out[", "net.if.total[",
            "perf_counter[\\network interface", "perf_counter_en[\\network interface",
            "huawei.oceanstor.v6.port.bps",
        ],
        "score": 65,
    },
}

# 硬排除：预测/阈值产物、系统信息类、字节数原始值——无论命中什么类别都不参与。
# 注意不得包含会误伤类别关键词的宽泛词（如裸 "total"、"status"）。
_EXCLUDE_KEYWORDS = [
    "timeleft", "forecast", "prediction",
    "dynamic_threshold",
    "vm.memory.size[total]", "vm.memory.size[used]",
    "vm.memory.size[free]", "vm.memory.size[available]",
    "uptime", "version", "hostname", "uname",
    "check", "ping", "packages.get",
    "maxfiles", "maxproc", "num",
    "interrupts per second", "intr",
    "cksum", "contents", "readonly", "operstate",
    "cache bytes", "memory size",
]

# 强降权：阈值/动态计算/负载细分等非实际观测值。
_DEMOTE_KEYWORDS = [
    "threshold", "阈值", "预警", "warn", "dynamic", "动态", "预测",
    "per_core", "avg1", "avg5", "avg15",
]

# 优先：百分比/使用率类关键词。
_PREFER_KEYWORDS = ["pavailable", "pused", "pfree", "utilization", "usage", "% used"]


def _drive_token(key: str) -> str:
    """提取磁盘项的分区标识用于去重（如 size[C:, -> C:；size[/boot, -> /boot）。"""
    if "size[" in key:
        return key.split("size[")[1].split(",")[0]
    return key


def _score(item: Dict[str, Any]) -> List[ScoredItem]:
    """对单个监控项评分；可能命中多个类别（返回多个 ScoredItem），也可能不命中。"""
    name_lower = str(item.get("name", "")).lower()
    key_lower = str(item.get("key_", "")).lower()

    for exclude in _EXCLUDE_KEYWORDS:
        if exclude in name_lower or exclude in key_lower:
            return []

    results: List[ScoredItem] = []
    for category, rule in _CATEGORY_RULES.items():
        hit = any(
            keyword in key_lower or keyword in name_lower
            for keyword in rule["keywords"]
        )
        if not hit:
            continue
        score = rule["score"]
        if any(prefer in key_lower or prefer in name_lower for prefer in _PREFER_KEYWORDS):
            score += 15
        if category == "disk":
            if "vfs.fs.dependent.size[" in key_lower:
                score += 20  # 空间使用率优先
            elif "vfs.fs.dependent.inode[" in key_lower:
                score -= 10  # inode 降权
        if category == "memory":
            if "pused]" in key_lower or "utilization" in key_lower or "usage" in key_lower:
                score += 15  # 使用率指标优先
            elif "available]" in key_lower or "free]" in key_lower:
                score -= 10  # 可用/剩余降权
            if "swap" in key_lower or "paging" in key_lower:
                score -= 40  # swap 与主内存区分
        if any(demote in name_lower or demote in key_lower for demote in _DEMOTE_KEYWORDS):
            score -= 50
        lastvalue = item.get("lastvalue")
        if lastvalue:
            try:
                if float(lastvalue) >= 0:
                    score += 10  # 有活跃数据
            except (TypeError, ValueError):
                pass
        if str(item.get("value_type", "")) in ("0", "3"):
            score += 5  # 数值类型便于趋势分析
        if score > 0:
            results.append(ScoredItem(category, score, item))
    return results


def select_key_metrics(
    items: List[Dict[str, Any]],
    *,
    max_disks: int = 10,
) -> Dict[str, List[ScoredItem]]:
    """从监控项列表中选出各类别关键指标。

    返回 {类别: [ScoredItem...]}：cpu/memory/disk_io/network 每类按分数取最佳
    一个；disk 按分区去重后取至多 max_disks 个，并按当前使用值降序排列。
    传入的 item 字典不会被修改。
    """
    scored: List[ScoredItem] = []
    for row in items:
        scored.extend(_score(row))
    scored.sort(key=lambda entry: entry.score, reverse=True)

    grouped: Dict[str, List[ScoredItem]] = {}
    seen_drives = set()
    for entry in scored:
        if entry.category == "disk":
            token = _drive_token(str(entry.item.get("key_", "")).lower())
            if token in seen_drives:
                continue
            if len(grouped.get("disk", [])) >= max_disks:
                continue
            seen_drives.add(token)
            grouped.setdefault("disk", []).append(entry)
        else:
            if entry.category not in grouped:
                grouped[entry.category] = [entry]

    if "disk" in grouped:
        grouped["disk"].sort(
            key=lambda entry: float(entry.item["lastvalue"] or 0)
            if str(entry.item.get("lastvalue", "")).replace(".", "", 1).replace("-", "", 1).isdigit()
            else 0,
            reverse=True,
        )
    return grouped
