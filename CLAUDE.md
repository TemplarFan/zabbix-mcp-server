# Zabbix MCP Server 开发指南

## 项目概述

这是一个基于 MCP (Model Context Protocol) 的 Zabbix 监控服务器，让 AI 助手能够通过自然语言查询和操作 Zabbix 监控系统。

**主要使用场景**：Dify + DeepSeek + 钉钉机器人

**Zabbix 版本**：7.0.x

---

## 重构进展

### 已完成的阶段

#### ✅ 阶段一 Step 1: 工具函数拆分
- [x] 创建 `src/utils/params.py` - 参数解析函数
- [x] 创建 `src/utils/format.py` - 格式化输出函数
- [x] 主文件改为从 utils 导入

#### ✅ 阶段二: Dify 体验优化
- [x] 新增 `get_problem_summary` - 告警摘要（Markdown 格式）
- [x] 新增 `check_host_health` - 主机健康检查
- [x] 新增 `quick_status` - 整体状态巡检

### 待完成

- [ ] 提取 `client.py` - Zabbix API 客户端封装
- [ ] 创建 `services/` 业务逻辑层
- [ ] 拆分 `tools/` 模块
- [ ] 创建 `main.py` 入口文件

---

## 项目结构

```
src/
├── zabbix_mcp_server.py    # 主文件，包含所有 MCP 工具
├── utils/                   # 工具函数模块 ✅
│   ├── __init__.py
│   ├── params.py           # 参数解析函数
│   └── format.py           # 格式化输出函数
└── tools/                   # 工具模块（预留）
    └── summary.py          # 摘要工具（已合并到主文件）

scripts/
├── start_server.py         # 启动脚本
└── test_server.py          # 测试脚本

config/
└── .env.example            # 环境变量模板
```

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

### 3. 主文件中的工具分类

#### 原始查询工具（返回 JSON）
- `host_get`, `host_create`, `host_update`, `host_delete`
- `item_get`, `item_create`, `item_update`, `item_delete`
- `trigger_get`, `trigger_create`, `trigger_update`, `trigger_delete`
- `problem_get`, `event_get`
- `history_get`, `trend_get`

#### 摘要工具（返回 Markdown，适合 Dify）
- `get_problem_summary` - 告警摘要（按严重程度统计）
- `check_host_health` - 主机健康检查（一站式）
- `quick_status` - 整体状态巡检

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

### quick_status

**用途**：快速查看整体状态（适合巡检）

**返回内容**：
- 主机在线/离线统计
- 告警分级统计

---

## 开发规范

### 添加新工具

在 `zabbix_mcp_server.py` 中添加：

```python
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

### 4. Dify 集成测试
- 更新 MCP 配置
- 测试对话：
  - "帮我看看整体状态"
  - "172.18.6.220 的健康状况"
  - "过去24小时的告警"

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

### Q: 如何调试
A: 查看日志输出，重点看：
- 参数解析是否正确
- Zabbix API 返回的错误信息
- 使用 DeepWiki 查询 API 限制

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

- v1.1.0 - 重构代码结构，新增摘要工具，修复 Zabbix 7.0 API 兼容性问题
- v1.0.0 - 基础功能实现

---

## 参考资源

- [Zabbix 7.0 API 文档](https://www.zabbix.com/documentation/7.0/en/manual/api/reference)
- [Zabbix GitHub 仓库](https://github.com/zabbix/zabbix) - 使用 DeepWiki 查询 API 定义
- [MCP Protocol](https://modelcontextprotocol.io/)
