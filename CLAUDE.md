# Zabbix MCP Server 开发指南

## 项目概述

这是一个基于 MCP (Model Context Protocol) 的 Zabbix 监控服务器，让 AI 助手能够通过自然语言查询和操作 Zabbix 监控系统。

**主要使用场景**：Dify + DeepSeek + 钉钉机器人

**Zabbix 版本**：7.0.x

---

## 重构进展

### 已完成的阶段

#### ✅ 阶段一: 代码结构改造
- [x] 创建 `src/utils/params.py` - 参数解析函数
- [x] 创建 `src/utils/format.py` - 格式化输出函数
- [x] 创建 `src/client.py` - Zabbix API 客户端封装
- [x] 创建 `src/main.py` - MCP 服务器入口文件
- [x] 拆分 `src/tools/` 模块
  - [x] `query.py` - 基础查询工具 (host_get, item_get, trigger_get, problem_get, event_get, history_get)
  - [x] `analysis.py` - 分析摘要工具 (trend_get, trend_summary, get_problem_summary, check_host_health, quick_status)
  - [x] `system.py` - 系统工具 (apiinfo_version, get_host_by_ip)

#### ✅ 阶段二: Dify 体验优化
- [x] 新增 `get_problem_summary` - 告警摘要（Markdown 格式）
- [x] 新增 `check_host_health` - 主机健康检查
- [x] 新增 `quick_status` - 整体状态巡检
- [x] 新增 `trend_summary` - 趋势统计摘要（省 Token）

#### ✅ 阶段三: 智能指标选择优化
- [x] 优化 `item_get` 的 `key_metrics_only` 智能评分算法
- [x] 支持用户实际的 Zabbix key 命名模式（`system.cpu.util`, `vm.memory.utilization`, `vfs.dev.util`）
- [x] 修复非数值型 `lastvalue` 导致的转换错误
- [x] 支持多厂商物理服务器（Huawei、Dell、HP、IPMI）
- [x] 添加 Windows `perf_counter_en` 英文性能计数器支持
- [x] 优化语义搜索，支持 `search_keyword` 智能匹配
- [x] 优化 `check_host_health` 磁盘分区显示（支持多分区、按使用率排序）
- [x] 修复 `check_host_health` 内存使用率显示（改为使用率而非可用空间）

### 待完成

- [ ] 创建 `services/` 业务逻辑层（可选）
- [ ] 添加更多数据库监控指标支持（Oracle, MySQL 等）

---

---

## 项目结构

```
src/
├── main.py                 # MCP 服务器入口文件 ✅
├── client.py               # Zabbix API 客户端封装 ✅
├── config.py               # 配置管理
├── zabbix_mcp_server.py    # 兼容层（原主文件）
├── utils/                  # 工具函数模块 ✅
│   ├── __init__.py
│   ├── params.py          # 参数解析函数
│   └── format.py          # 格式化输出函数
└── tools/                  # MCP 工具模块 ✅
    ├── __init__.py
    ├── query.py           # 基础查询工具
    ├── analysis.py        # 分析摘要工具
    └── system.py          # 系统工具

scripts/
├── start_server.py         # 启动脚本
└── test_server.py          # 测试脚本

config/
├── prompt.md               # Dify 提示词配置
└── .env.example            # 环境变量模板
```

---

---

## 核心模块说明

### 1. utils/params.py - 参数解析

处理 LLM 传来的各种参数格式：

```python
from utils.params import (
    parse_int_param,      # "123" -> 123
    parse_time_param,     # "1h" / "24h" / "yesterday" -> Unix timestamp
    parse_list_param,     # "[a,b]" / "a,b" -> [a, b]
    parse_dict_param,     # JSON string -> dict
)
```

### 2. utils/format.py - 格式化输出

为 LLM 优化的输出格式：

```python
from utils.format import (
    format_response,      # JSON 格式化
    format_table,         # Markdown 表格
)
```

### 3. 工具模块分类

#### tools/query.py - 基础查询工具（返回 JSON）
- `host_get` - 查询主机列表
- `item_get` - 查询监控项（支持 `key_metrics_only` 智能筛选）
- `trigger_get` - 查询触发器
- `problem_get` - 查询当前告警
- `event_get` - 查询事件
- `history_get` - 查询历史数据

#### tools/analysis.py - 分析摘要工具（返回 Markdown）
- `get_problem_summary` - 告警摘要（按严重程度统计）
- `check_host_health` - 主机健康检查（一站式）
- `quick_status` - 整体状态巡检
- `trend_get` - 查询详细趋势数据
- `trend_summary` - 趋势统计摘要（省 Token）

#### tools/system.py - 系统工具
- `apiinfo_version` - 查询 Zabbix API 版本
- `get_host_by_ip` - 通过 IP 地址查询主机

---

## Zabbix 7.0 API 限制

### problem.get 限制

根据 Zabbix 7.0 源代码（`zabbix/zabbix` 仓库）：

| 参数 | 支持情况 | 说明 |
|------|----------|------|
| `sortfield` | ⚠️ 只支持 `eventid` | 不支持 `severity`、`clock` 等 |
| `selectHosts` | ❌ 不支持 | 无法直接获取主机信息 |
| `time_from`/`time_till` | ✅ 支持 | UNIX 时间戳（秒） |
| `selectAcknowledges` | ✅ 支持 | 获取确认信息 |

**获取主机信息的替代方案：**
1. 通过 `objectid` 查询 `trigger.get` + `selectHosts`
2. 或使用 `event.get`（支持 `selectHosts`）

### event.get vs problem.get

| 特性 | problem.get | event.get |
|------|-------------|-----------|
| 用途 | 当前活动问题 | 所有事件 |
| `selectHosts` | ❌ | ✅ |
| 排序字段 | 仅 `eventid` | 更多选项 |

---

## 新增摘要工具说明

### get_problem_summary

**用途**：查询告警摘要，返回 Markdown 格式

**参数**：
- `hostids`: 主机ID（可选，逗号分隔）
- `time_range`: 时间范围，支持 "1h", "24h", "7d", "yesterday"
- `group_by`: 分组方式（默认按严重程度）

**返回示例**：
```markdown
## 告警概览

**总计: 5 个告警**

🔴 严重: 2个
🟠 一般: 3个

### 最严重的5个告警
| 时间     | 主机   | 问题         | 级别 |
|----------|--------|--------------|------|
| 03-11 09:30 | server-01 | CPU使用率超过阈值 | 严重 |
```

**实现细节**：
- 使用 `problem.get` 获取告警列表
- 通过 `trigger.get` + `selectHosts` 批量获取主机名（性能优化）
- 本地按 severity 排序（API 不支持）

**Dify 提示词建议**：
```
优先使用 get_problem_summary 查询告警，
它比 problem_get 更适合对话展示
```

### check_host_health

**用途**：一站式检查主机健康状况

**参数**：
- `host_identifier`: IP / 主机名 / hostid（自动识别）
- `time_range`: 查询时间范围

**返回内容**：
- 主机基本信息（IP、状态）
- 当前告警列表
- 关键指标（CPU/内存/磁盘）

### check_host_health 详细说明

**用途**：一站式检查主机健康状况，自动识别多平台监控项

**支持的平台**：
| 平台 | Key 模式 | 示例 |
|------|----------|------|
| Linux (Agent2) | `system.cpu.util`, `vm.memory.size[pused]`, `vfs.fs.dependent.size` | CPU使用率、内存使用率、分区使用率 |
| Windows | `perf_counter[\Processor`, `perf_counter[\Memory`, `perf_counter[\LogicalDisk` | 英文/中文性能计数器 |
| Huawei 服务器 | `huawei-server.systemCpuUsage`, `huawei-server.systemMemUsage` | iBMC 监控 |
| IPMI | `ipmi.sensor[...]` | 硬件传感器 |

**磁盘显示优化**（2025-03-19 更新）：
- 支持最多 **10个分区**，自动去重（按盘符/挂载点）
- 按**使用率从高到低**排序，优先显示空间紧张的分区
- 自动简化分区名称：`FS [/usr]` → `/usr分区使用率`
- 自动过滤 inode 监控项，仅显示空间使用率

**内存显示优化**（2025-03-19 更新）：
- 统一显示**内存使用率**（已使用百分比）
- Linux: `vm.memory.size[pused]`
- Windows: `perf_counter[\Memory\% Committed Bytes In Use]`
- 自动过滤 swap/paging 相关指标

**使用示例**：
```python
# 通过 IP 查询
check_host_health(host_identifier="172.18.3.105")

# 通过主机名查询
check_host_health(host_identifier="server-01")

# 通过 hostid 查询
check_host_health(host_identifier="10623")
```

**返回示例**：
```markdown
## 主机健康检查: server-01

### 基本信息
- **主机名**: server-01
- **IP**: 172.18.3.105
- **状态**: 在线

### 当前告警
| 时间 | 问题 | 级别 |
|------|------|------|
| 03-19 10:30 | CPU使用率超过阈值 | 严重 |

### 关键指标

**CPU使用率**: 78.5%

**内存使用率**: 65.2%

**磁盘使用率**:
| 分区 | 使用率 |
|------|--------|
| C: | 85.3% |
| D: | 45.2% |
| E: | 12.1% |
```

### quick_status

**用途**：快速查看整体状态（适合巡检）

**返回内容**：
- 主机在线/离线统计
- 告警分级统计

### trend_summary

**用途**：获取趋势统计摘要（极省 Token）

相比 `trend_get`（返回详细时间序列），`trend_summary` 只返回：
- 当前值、平均值/最大值/最小值
- 趋势判断（上升/下降/平稳）
- 关键时间点

**参数**：
- `itemids`: 监控项ID（最多3个，防止Token溢出）
- `hours`: 查询时长（默认24小时）
- `include_analysis`: 是否包含趋势分析和建议

---

## 智能指标选择算法

### item_get 的 key_metrics_only 模式

当 `key_metrics_only=true` 时，`item_get` 使用智能评分算法自动选择关键性能指标（CPU/内存/磁盘）。

### 评分规则

算法基于以下类别对监控项进行评分：

| 类别 | 关键字匹配 | 分值 |
|------|-----------|------|
| CPU使用率 | `cpu.util`, `system.cpu.util`, `system.cpu.load`, `perf_counter[\processor`, `perf_counter_en[\processor`, `huawei-server.systemCpuUsage`, `ipmi.sensor` | 100 |
| 内存使用率 | `memory.util`, `memory.utilization`, `vm.memory.size[pavailable]`, `vm.memory.size[pused]`, `perf_counter[\memory`, `perf_counter_en[\memory`, `huawei-server.systemMemUsage`, `ipmi.sensor` | 95 |
| 磁盘使用率 | `vfs.fs.dependent.size[pused]`, `vfs.fs.dependent.inode[pfree]`, `vfs.fs.dependent.inode[pused]`, `perf_counter[\logicaldisk`, `perf_counter_en[\logicaldisk`, `dell.server.hw.physicaldisk` | 95 |
| 磁盘IO | `vfs.dev.io`, `vfs.dev.read`, `vfs.dev.write`, `vfs.dev.queue`, `perf_counter[\physicaldisk` | 70 |
| 网络流量 | `net.if.in`, `net.if.out`, `net.if.total`, `perf_counter[\network interface` | 65 |
| 进程数量 | `proc.num` | 30 |
| 预测类 | `timeleft`, `forecast` | 10（降权） |

### 支持的硬件类型

`key_metrics_only` 自动识别以下硬件监控类型：

| 类型 | Key 前缀/模式 | 示例 |
|------|--------------|------|
| Linux 标准 | `system.cpu.*`, `vm.memory.*`, `vfs.fs.*` | `system.cpu.load`, `vm.memory.size[pavailable]` |
| Windows 性能计数器 | `perf_counter[\*`, `perf_counter_en[\*` | `perf_counter_en[\Processor(_Total)\% Processor Time]` |
| Huawei 服务器 | `huawei-server.*`, `huawei.5300.v5[*` | `huawei-server.systemCpuUsage` |
| Dell 服务器 | `dell.server.*` | `dell.server.hw.physicaldisk` |
| IPMI 传感器 | `ipmi.sensor.*` | `ipmi.sensor[CPU1_Temp]` |
| 通用 SNMP | `snmp.*` | `snmp.cpu[cpuUsage]` |

### 降权规则

- **非核心指标**: 包含 `uptime`, `version`, `check`, `status` 等关键词减 30 分
- **阈值/动态计算**: 包含 `threshold`, `阈值`, `dynamic`, `动态` 等关键词减 50 分
- **活跃状态**: 有最新数据且为数值型加 10 分

### 使用示例

```python
# 获取主机的关键指标
item_get(hostids="12345", key_metrics_only=true, limit=10)
```

**输出**：自动返回 CPU、内存、磁盘等关键指标，排除阈值、预测类指标。

---

## 语义搜索功能

### item_get 的 search_keyword 参数

`item_get` 支持通过 `search_keyword` 参数进行自然语言搜索，自动映射到 Zabbix key 模式：

```python
# 搜索磁盘相关指标
item_get(hostids="12345", search_keyword="disk usage")

# 搜索内存相关指标
item_get(hostids="12345", search_keyword="memory")

# 搜索网络流量
item_get(hostids="12345", search_keyword="network traffic")
```

### 语义映射表

| 关键词 | 匹配的 Key 模式 |
|--------|----------------|
| memory, 内存 | `*vm.memory*`, `*\memory\*`, `*perf_counter*memory*`, `*huawei*mem*usage*`, `*ipmi*memory*` |
| cpu, processor, 处理器 | `*system.cpu*`, `*\processor\*`, `*perf_counter*processor*`, `*huawei*cpu*usage*`, `*ipmi*cpu*` |
| disk, space, storage, 磁盘 | `*vfs.fs.dependent.size*`, `*vfs.fs.dependent.inode*`, `*\logicaldisk\*`, `*dell*disk*`, `*hardware*disk*` |
| disk io, io | `*vfs.dev.io*`, `*vfs.dev.read*`, `*vfs.dev.write*`, `*vfs.dev.queue*`, `*physicaldisk*` |
| network, traffic | `*net.if.in*`, `*net.if.out*`, `*net.if.total*`, `*network interface*` |
| load, 负载 | `*system.cpu.load*`, `*cpu.load*` |

### 与 key_metrics_only 结合使用

```python
# 先通过语义搜索找到相关监控项，再用 key_metrics_only 筛选关键指标
item_get(hostids="12345", search_keyword="disk", key_metrics_only=true, limit=10)
```

## 开发规范

### 添加新工具

在 `src/tools/` 目录下相应的文件中添加：

```python
# src/tools/query.py
from client import get_zabbix_client
from utils.params import parse_int_param, parse_list_param
from utils.format import format_response

@mcp.tool()
def my_new_tool(param: str) -> str:
    """
    工具描述

    Args:
        param: 参数说明

    Returns:
        返回说明
    """
    client = get_zabbix_client()
    # 业务逻辑
    return format_response(result)
```

然后在 `src/tools/__init__.py` 中导出：

```python
from tools.query import my_new_tool
```

最后在 `src/main.py` 中注册：

```python
from tools import my_new_tool
mcp.tool()(my_new_tool)
```

### 工具分类原则

1. **原始工具**：返回原始 JSON，参数完整，用于高级查询
2. **摘要工具**：返回 Markdown，参数简化，用于对话场景

### API 参数验证

添加新工具时，务必查阅 Zabbix API 文档：

```bash
# 使用 DeepWiki 查询 Zabbix 源码 API 定义
# 询问：Zabbix API problem.get 参数说明
```

常用查询：
- `problem.get` 支持字段：`eventid`, `source`, `object`, `objectid`, `clock`, `ns`, `r_eventid`, `r_clock`, `r_ns`, `correlationid`, `userid`, `name`, `acknowledged`, `severity`, `cause_eventid`, `opdata`, `suppressed`, `urls`

---

## 测试方法

### 1. 本地导入测试
```bash
uv run python -c "from src.zabbix_mcp_server import get_problem_summary"
```

### 2. 启动服务器测试
```bash
uv run python scripts/start_server.py
```

### 3. MCP Inspector 测试
```bash
npx @modelcontextprotocol/inspector
```

### 4. 测试不同主机类型

```bash
# 测试 Linux 主机（Zabbix Agent2）
uv run python -c "
from src.tools.query import item_get
print(item_get(hostids='10623', key_metrics_only=True, limit=10))
"

# 测试 Windows 主机（perf_counter）
uv run python -c "
from src.tools.query import item_get
print(item_get(hostids='10624', search_keyword='cpu', key_metrics_only=True))
"

# 测试 Huawei 服务器
uv run python -c "
from src.tools.query import item_get
print(item_get(hostids='10625', key_metrics_only=True))
"

# 测试语义搜索
uv run python -c "
from src.tools.query import item_get
print(item_get(hostids='10623', search_keyword='disk usage', limit=5))
"
```

---

## 常见问题

### Q: 工具调用报错 "unexpected parameter"
A: Zabbix API 不支持某些参数（如 `selectHosts` 在 `problem.get` 中），需要移除

### Q: 工具调用报错 "/sortfield/1: value must be eventid"
A: `problem.get` 只支持按 `eventid` 排序，需要在 Python 中本地排序

### Q: LLM 说工具不可用
A:
1. 重启 MCP 服务器（修改代码后必须重启）
2. 检查 Dify 是否正确加载工具列表
3. 查看服务器日志确认错误

### Q: 为什么查不到某些监控项
A: 检查以下几点：
1. 确认主机使用的 Zabbix Agent 版本（Agent 6.0 和 7.0 的 key 命名可能不同）
2. Linux 主机可能使用 `vfs.fs.dependent.size` 而非 `vfs.fs.size`
3. Windows 主机可能使用 `perf_counter_en` 而非 `perf_counter`
4. 物理服务器可能使用厂商特定的 key（如 `huawei-server.*`, `dell.server.*`）

### Q: key_metrics_only 返回的结果不准确
A: 可以通过以下方式调试：
1. 先不用 `key_metrics_only`，查看所有监控项的 `key_` 字段
2. 确认目标指标的 key 命名模式
3. 在 `src/tools/query.py` 的 `category_rules` 中添加新的关键字匹配

### Q: 如何添加新的硬件类型支持
A: 编辑 `src/tools/query.py`：
1. 在 `category_rules` 中的相应类别添加新的关键字匹配
2. 在 `semantic_map` 中添加语义搜索关键词
3. 重启 MCP 服务器

### Q: 为什么某些主机查不到磁盘数据
A: 可能原因：
1. **Zabbix Agent 版本过低**：`vfs.fs.dependent.discovery` 需要 Agent 3.4+，旧版本（如 3.0.x）不支持
2. **未配置监控项**：确保主机已应用 Template OS Linux/Windows 模板
3. **Agent 未运行**：检查目标主机的 Agent 服务状态

**诊断方法**：
```bash
# 查看主机支持的监控项
item_get(hostids="12345", search_keyword="vfs.fs")

# 如果没有返回结果，说明 Agent 版本问题或模板未应用
```

**解决方案**：
- 升级 Zabbix Agent 到 6.0+ 或 7.0+
- 确认模板已正确应用到主机

---

## 环境变量

```bash
ZABBIX_URL=https://your-zabbix.com
ZABBIX_TOKEN=your-token
# 或
ZABBIX_USER=admin
ZABBIX_PASSWORD=password

READ_ONLY=true          # 只读模式
VERIFY_SSL=true         # SSL 验证

# MCP 传输配置
ZABBIX_MCP_TRANSPORT=stdio        # 或 streamable-http
ZABBIX_MCP_HOST=127.0.0.1
ZABBIX_MCP_PORT=8000
```

---

## 版本历史

- v1.3.1 - 优化 `check_host_health`：支持多分区显示（最多10个）、按使用率排序、内存显示改为使用率
- v1.3.0 - 支持多厂商物理服务器（Huawei、Dell、HP、IPMI），添加语义搜索功能，支持 Windows `perf_counter_en`
- v1.2.0 - 优化智能指标选择算法，支持用户实际 Zabbix key 命名模式
- v1.1.0 - 重构代码结构，新增摘要工具，修复 Zabbix 7.0 API 兼容性问题
- v1.0.0 - 基础功能实现

---

## 参考资源

- [Zabbix 7.0 API 文档](https://www.zabbix.com/documentation/7.0/en/manual/api/reference)
- [Zabbix GitHub 仓库](https://github.com/zabbix/zabbix) - 使用 DeepWiki 查询 API 定义
- [MCP Protocol](https://modelcontextprotocol.io/)
