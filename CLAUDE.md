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
  - [x] `query.py` - 基础查询工具 (host_get, item_get, trigger_get, event_get, history_get)
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

#### ✅ 阶段四: 工具描述与翻页优化（2026-03-26）
- [x] 优化 `get_problem_summary` 和 `event_get` 的工具描述，明确划分使用边界
- [x] 添加 `event_get` 智能翻页机制，返回翻页元数据帮助 LLM 判断是否继续
- [x] 修复 `event_get` 时间参数解析，使用 `parse_time_param` 支持相对时间（如 "24h", "7d"）
- [x] 修复翻页时 `time_from` 被重新计算的问题，要求使用绝对时间戳翻页
- [x] 优化"是否还有更多"判断逻辑（返回数量 < limit 时停止）
- [x] 翻页结束时返回明确的停止指令
- [x] 明确 `value` 参数含义（`value=1` 问题发生，`value=0` 问题已恢复）
- [x] 添加 Dify 提示词配置，强制要求直接展示摘要工具结果

### 待完成

- [ ] 创建 `services/` 业务逻辑层（可选）
- [ ] 添加更多数据库监控指标支持（Oracle, MySQL 等）

---

## 项目结构

```
src/
├── main.py                 # MCP 服务器入口文件
├── client.py               # Zabbix API 客户端封装
├── config.py               # 配置管理
├── zabbix_mcp_server.py    # 兼容层（原主文件）
├── utils/                  # 工具函数模块
│   ├── __init__.py
│   ├── params.py          # 参数解析函数
│   └── format.py          # 格式化输出函数
└── tools/                  # MCP 工具模块
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

## 核心模块说明

### 1. utils/params.py - 参数解析

处理 LLM 传来的各种参数格式：

```python
from utils.params import (
    parse_int_param,           # "123" -> 123
    parse_time_param,          # "1h" / "24h" / "7d" -> Unix timestamp
    parse_list_param,          # "[a,b]" / "a,b" -> [a, b]
    parse_dict_param,          # JSON string -> dict
    parse_list_of_dicts_param, # JSON array -> List[Dict]
)
```

### 2. utils/format.py - 格式化输出

为 LLM 优化的输出格式：

```python
from utils.format import (
    format_response,      # JSON 格式化（带缩进）
    format_table,         # Markdown 表格（自动对齐）
    format_problem_summary,  # 告警摘要格式化
    format_host_overview,    # 主机概览格式化
)
```

### 3. 工具模块分类

#### tools/query.py - 基础查询工具（返回 JSON）

| 工具 | 用途 | 关键参数 |
|------|------|---------|
| `host_get` | 查询主机列表 | `name` 模糊搜索，`groupids` 按组筛选 |
| `item_get` | 查询监控项 | `key_metrics_only` 智能筛选，`search` 语义搜索 |
| `trigger_get` | 查询触发器 | `priority` 按级别筛选，`include_expression` 包含表达式 |
| `event_get` | 查询历史事件 | `time_from/time_till` 时间范围，`value` 状态过滤 |
| `history_get` | 查询原始历史数据 | `history` 数据类型，`time_from` 支持相对时间 |

#### tools/analysis.py - 分析摘要工具（返回 Markdown）

| 工具 | 用途 | 返回格式 |
|------|------|---------|
| `get_problem_summary` | 当前未确认告警摘要 | Markdown 表格（按严重程度分组） |
| `check_host_health` | 主机健康检查 | Markdown 报告（告警+关键指标） |
| `quick_status` | 整体状态巡检 | Markdown 统计（主机+告警） |
| `trend_get` | 详细趋势数据 | JSON（每小时聚合数据） |
| `trend_summary` | 趋势统计摘要 | Markdown 表格（省 Token） |

#### tools/system.py - 系统工具

| 工具 | 用途 |
|------|------|
| `apiinfo_version` | 查询 Zabbix API 版本 |
| `get_host_by_ip` | 通过 IP 地址精确查询主机（最省 Token） |

---

## Zabbix 7.0 API 限制与特性

### problem.get 限制

| 参数 | 支持情况 | 说明 |
|------|----------|------|
| `sortfield` | ⚠️ 只支持 `eventid` | 不支持 `severity`、`clock` 等 |
| `selectHosts` | ❌ 不支持 | 无法直接获取主机信息 |
| `time_from`/`time_till` | ✅ 支持 | UNIX 时间戳（秒） |
| `acknowledged` | ✅ 支持 | 过滤已/未确认问题 |
| `suppressed` | ✅ 支持 | 过滤被抑制的问题 |

### event.get 特性

| 特性 | 说明 |
|------|------|
| `selectHosts` | ✅ 支持（与 problem.get 不同） |
| `sortfield` | ✅ 支持 `clock` 等多种字段 |
| `value` | 0=问题已恢复, 1=问题发生 |
| 翻页 | 通过 `time_till` 向前翻页 |

---

## 工具使用详解

### get_problem_summary

**用途**：查询当前未确认告警列表（与 Zabbix 仪表盘"未确认问题"视图一致）

**参数**：
- `hostids`: 主机ID（可选，不传则查询所有主机；逗号分隔多个主机）
- `time_range`: 时间范围（仅用于标题显示，可选，默认"24h"）
- `group_by`: 分组方式（默认按严重程度）

**返回示例**：
```markdown
## 告警概览 (24h)

**总计: 6 个未确认告警**

🟠 一般: 1个
🟡 警告: 3个
🔵 信息: 1个
⚪ 未分类: 1个

---

### 🟠 一般级别 (1个)

| 时间 | 主机 | 问题 |
|------|------|------|
| 03-20 16:53 | 猪齿鱼平台k8s服务器节点4 172.18.15.31 | Linux: Interface calied1618bfdfc: Link down |

### 🟡 警告级别 (3个)

| 时间 | 主机 | 问题 |
|------|------|------|
| 03-24 09:27 | lims数据库 172.18.6.137 | 1 D:: Disk is overloaded |
| 03-23 22:22 | 棒材PES系统应用 172.18.6.34 | Linux: FS [/home]: Space is low |
```

**实现细节**：
- 使用 `problem.get` 获取未确认问题（`acknowledged=False`）
- 过滤被抑制的问题（`suppressed=False`）
- 通过 `trigger.get` + `selectHosts` 批量获取主机名
- 本地按 severity 降序排序（API 不支持）
- 过滤禁用主机的问题

### check_host_health

**用途**：一站式检查主机健康状况

**参数**：
- `host_identifier`: IP / 主机名 / hostid（自动识别）
- `time_range`: 查询告警的时间范围（默认"24h"）
- `include_trends`: 是否包含趋势数据（默认 False）
- `trend_hours`: 趋势数据查询时长（默认 24）
- `include_oracle`: 是否查询 Oracle 相关指标（默认 False）

**主机识别逻辑**：
1. 尝试作为 hostid 精确匹配
2. 尝试作为 IP 地址匹配（通过 `hostinterface.get`）
3. 尝试作为主机名精确匹配
4. 使用 `search` 子串搜索主机名
5. 从输入中提取 IP 地址进行匹配

**智能评分算法**：

代码中定义了 `category_rules` 对监控项进行评分：

| 类别 | 关键字匹配 | 分值 |
|------|-----------|------|
| CPU | `system.cpu.util`, `perf_counter[\processor`, `huawei-server.systemCpuUsage`, `ipmi.sensor` | 100 |
| 内存 | `vm.memory.size[pused]`, `perf_counter[\memory`, `huawei-server.systemMemUsage` | 95 |
| 磁盘 | `vfs.fs.dependent.size[pused]`, `perf_counter[\logicaldisk` | 95 |
| 网络 | `net.if.in[`, `net.if.out[` | 65 |

**磁盘显示优化**：
- 支持最多 **10个分区**
- 自动去重（按盘符/挂载点）
- 按使用率从高到低排序
- 自动简化分区名称：`FS [/usr]` → `/usr分区使用率`

**内存显示优化**：
- 统一显示**内存使用率**（已使用百分比）
- 自动过滤 swap/paging 相关指标

### event_get 翻页机制

**重要区分**：
- `get_problem_summary`: 当前未解决问题 → 直接展示
- `event_get`: 历史事件（包括已恢复的）→ 需要翻页

**翻页逻辑**：

```
第1次: event_get(hostids="12345", time_from="7d", limit=50)
       → 返回最新的50条
       → 记录返回的 time_from 绝对值（如 1774275680）

第2次: event_get(hostids="12345", time_from=1774275680, time_till=1774275679, limit=50)
       → 使用绝对时间戳翻页，返回更早的50条

第3次: event_get(hostids="12345", time_from=1774275680, time_till=新时间戳-1, limit=50)
       → 继续用绝对时间戳翻页...
```

**关键修复**：翻页时必须使用**绝对时间戳**（如 `1774275680`），不能用相对时间（如 `"7d"`），因为相对时间每次都会重新计算，导致时间窗口不一致。

**何时停止翻页（重要）**：
- 当翻页信息中显示"是否还有更多: 否"时，**必须立即停止翻页**
- 当"返回数量 < limit"时，说明该时间范围内已获取全部数据
- 当"最早记录时间"已接近"查询范围"起点时，停止翻页

**返回翻页元数据**：
```json
/* 翻页信息（不要展示给用户）：
- 本次返回: 50 条记录 (limit=50)
- 最早记录时间: 1774275680 (2026-03-22 10:00:00)
- 查询范围: 1773660800 到 现在
- 是否还有更多: 否（返回数量少于limit，已获取全部数据）
- 【重要】请停止翻页，直接基于已获取的 50 条记录进行分析和总结
*/

[
  {"eventid": "...", "name": "...", "clock": "1774275680"},
  ...
]
```

### item_get 语义搜索

**语义映射表**：

| 关键词 | 匹配的 Key 模式 |
|--------|----------------|
| memory, 内存 | `*vm.memory*`, `*\memory\*`, `*perf_counter*memory*`, `*huawei*mem*usage*` |
| cpu, processor | `*system.cpu*`, `*\processor\*`, `*perf_counter*processor*`, `*huawei*cpu*usage*` |
| disk, space | `*vfs.fs.dependent.size*`, `*vfs.fs.dependent.inode*`, `*\logicaldisk\*` |
| disk io | `*vfs.dev.io*`, `*vfs.dev.read*`, `*\physicaldisk\*` |
| network | `*net.if.in*`, `*net.if.out*`, `*\network\*` |

**key_metrics_only 模式**：

智能评分筛选关键性能指标：
- 排除预测类指标（`timeleft`, `forecast`）
- 排除阈值类指标（`dynamic_threshold`, `threshold`）
- 排除系统信息类（`uptime`, `version`, `check`）
- 优先选择使用率指标（`pused`, `utilization`, `usage`）
- 每个核心类别（CPU/内存/磁盘）最多选1个最佳指标

---

## Dify 提示词配置

在 `config/prompt.md` 中定义了工具选择指南和结果展示规则：

### 工具选择指南

| 用户提问 | 应该调用的工具 | 说明 |
|---------|--------------|------|
| "有没有告警" | `get_problem_summary` | 直接返回摘要 |
| "某主机怎么样" | `check_host_health` | 一站式检查 |
| "整体状态" | `quick_status` | 快速巡检 |
| "某指标的趋势" | 三步调用链 | host_get → item_get → trend_summary |

### 结果展示规则（重要）

**必须原样展示的工具**：
- `get_problem_summary` - Markdown 表格，**禁止总结**
- `check_host_health` - Markdown 报告，**禁止概括**
- `quick_status` - Markdown 统计，**禁止提炼**

**禁止行为**：
- ❌ 不要把表格改成文字描述
- ❌ 不要说"以下是查询结果"然后只给总结
- ❌ 不要只列"主要问题"

---

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

然后在 `src/tools/__init__.py` 中导出，在 `src/main.py` 中注册。

### 工具分类原则

1. **原始工具**（query.py）：返回原始 JSON，参数完整，用于高级查询
2. **摘要工具**（analysis.py）：返回 Markdown，参数简化，用于对话场景
3. **系统工具**（system.py）：通用功能，如版本查询、主机定位

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
1. 确认主机使用的 Zabbix Agent 版本
2. Linux 主机可能使用 `vfs.fs.dependent.size` 而非 `vfs.fs.size`
3. Windows 主机可能使用 `perf_counter_en` 而非 `perf_counter`
4. 物理服务器可能使用厂商特定的 key（如 `huawei-server.*`, `dell.server.*`）

### Q: key_metrics_only 返回的结果不准确
A: 调试步骤：
1. 先不用 `key_metrics_only`，查看所有监控项的 `key_` 字段
2. 确认目标指标的 key 命名模式
3. 在 `src/tools/query.py` 的 `category_rules` 中添加新的关键字匹配

### Q: 为什么某些主机查不到磁盘数据
A: 可能原因：
1. **Zabbix Agent 版本过低**：`vfs.fs.dependent.discovery` 需要 Agent 3.4+
2. **未配置监控项**：确保主机已应用 Template OS Linux/Windows 模板
3. **Agent 未运行**：检查目标主机的 Agent 服务状态

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

- **v1.4.1** (2026-03-26) - 修复 `event_get` 时间参数解析和翻页机制
  - 使用 `parse_time_param` 支持相对时间字符串（"24h", "7d"）
  - 修复翻页时 `time_from` 被重新计算的问题
  - 优化"是否还有更多"判断逻辑（返回数量 < limit 时停止）
  - 翻页结束时返回明确的停止指令
- **v1.4.0** (2025-03-24) - 优化工具描述与翻页机制，添加 Dify 提示词配置
- **v1.3.1** (2025-03-19) - 优化 `check_host_health`：支持多分区显示、按使用率排序、内存显示改为使用率
- **v1.3.0** (2025-03-18) - 支持多厂商物理服务器（Huawei、Dell、HP、IPMI），添加语义搜索功能
- **v1.2.0** (2025-03-15) - 优化智能指标选择算法，支持用户实际 Zabbix key 命名模式
- **v1.1.0** (2025-03-10) - 重构代码结构，新增摘要工具，修复 Zabbix 7.0 API 兼容性问题
- **v1.0.0** (2025-03-01) - 基础功能实现

---

## 参考资源

- [Zabbix 7.0 API 文档](https://www.zabbix.com/documentation/7.0/en/manual/api/reference)
- [Zabbix GitHub 仓库](https://github.com/zabbix/zabbix)
- [MCP Protocol](https://modelcontextprotocol.io/)
