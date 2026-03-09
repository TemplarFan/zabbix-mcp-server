# Dify + MCP + Zabbix 智能运维助手研究汇报

## 项目概述

本项目构建了一个基于 **Dify + MCP (Model Context Protocol) + DeepSeek 大模型** 的智能运维助手，实现对 Zabbix 监控系统的自然语言交互式查询。

### 核心价值
- **自然语言交互**：用户无需记忆复杂的 Zabbix API，通过自然语言即可查询监控数据
- **上下文感知**：基于 MCP 协议，大模型可以调用 Zabbix 的实时数据
- **中文优化**：针对中文运维场景优化提示词和输出格式

---

## 技术架构

### 架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户交互层                               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │ Web 界面    │  │ 移动端      │  │ 第三方 IM (企业微信等)  │  │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Dify 智能体平台                          │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                   Agent 配置                           │    │
│  │  • 模型：DeepSeek-V3 / DeepSeek-R1                    │    │
│  │  • 温度：0.3 (低随机性，确保准确性)                    │    │
│  │  • 最大 Token：4096                                   │    │
│  └─────────────────────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                   MCP 工具集成                         │    │
│  │  • host_get, get_host_by_ip                             │    │
│  │  • problem_get                                          │    │
│  │  • history_get, trend_get                               │    │
│  │  • inspect_host_performance                             │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      MCP Server (stdio)                         │
│         zabbix-mcp-server (Python + FastMCP)                  │
│              提供 40+ Zabbix API 工具封装                       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Zabbix 监控系统                            │
│  • Host / Item / Trigger / Event                               │
│  • History / Trend / Problem                                   │
│  • User / Proxy / Maintenance                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 组件说明

| 组件 | 技术栈 | 职责 |
|------|--------|------|
| **前端交互** | Dify Chat / Web / IM | 用户自然语言输入和结果展示 |
| **智能体引擎** | Dify + DeepSeek | 意图识别、工具选择、结果总结 |
| **MCP Server** | Python + FastMCP | 封装 Zabbix API，提供标准化工具 |
| **监控系统** | Zabbix 6.0+ | 实际的监控数据存储和查询 |

---

## Dify 智能体配置

### 1. 基础模型配置

```yaml
模型: DeepSeek-V3 (或 DeepSeek-R1)
API Endpoint: https://api.deepseek.com/v1/chat/completions
温度: 0.3
最大 Token: 4096
```

### 2. 提示词设计 (System Prompt)

```markdown
你是一个专业的 Zabbix 智能运维助手。你可以通过 MCP 工具访问 Zabbix 监控系统的数据。

## 你的能力
1. 查询主机状态、列表和配置 (host_get,get_host_by_ip)。
2. 查询当前的告警和问题 (problem_get)
3. 获取监控项的历史数据和趋势 (history_get, trend_get)
4. 主机的整体数据(inspect_host_performance)
5. 搜索监控项时，用英文搜索关键词

## 回答规范
- 必须用中文输出，和最后总结的反馈
- 当用户询问"某台服务器"的情况时，如果涉及到IP地址，先尝试用get_host_by_ip获取hostid，否则再尝试提取主机名，并通过`host_get`的name参数模糊搜索主机名获取 hostid。
- 如果查询到告警信息，请按严重程度排序，并给出具体的告警时间、名称和主机。
- 如果是查询`具体某一项`的历史数据，则调用history_get
- 如果是查询`具体某一项`的趋势，则调用trend_get
- 如果是查询`整体情况`，则调用inspect_host_performance
- 在展示数据时，尽量使用清晰的列表或 Markdown 表格。
- 如果未查到数据，请提示用户检查主机名是否正确。

## 限制规则
- 每个session中，第一次使用get_host_by_ip/host_get查询主机id后，应该记住这些主机id，留给后续的任务重复使用
- 分析任务需求，并找到最适合的工具
- 每次任务最多只能调用5次工具
- 如果调用5次工具依然没有获得结果，直接返回错误信息并给出优化建议

## 示例场景
### 示例1
用户: "帮我看看 情报系统应用文件服务器 172.18.6.220有没有报警"
思考: 因为涉及到IP地址，先调用get_host_by_ip找到172.18.6.220的 hostid，然后用 hostid 调用 problem_get，并对返回的结果进行总结。

### 示例2
用户: "帮我看看能源正式环境有没有报警"
思考: 分析主机名为能源正式环境，但没有涉及到IP地址，调用host_get通过参数name=能源正式环境进行模糊匹配获得hostid，如果返回了多个，则直接输出主机名和IP询问具体查询哪一个，如果只返回一个结果则用 hostid 调用 problem_get，并对返回的结果进行总结。
```

### 3. MCP Server 配置

在 Dify 的 MCP Server 配置中添加：

```json
{
  "command": "uv",
  "args": [
    "run",
    "--directory",
    "/path/to/zabbix-mcp-server",
    "python",
    "src/zabbix_mcp_server.py"
  ],
  "env": {
    "ZABBIX_URL": "https://zabbix.example.com",
    "ZABBIX_TOKEN": "your_api_token",
    "READ_ONLY": "true"
  }
}
```

---

## 关键技术实现

### 1. MCP Server 工具封装

MCP Server (`src/zabbix_mcp_server.py`) 封装了 40+ 个 Zabbix API 工具：

```python
@mcp.tool()
def host_get(
    hostids: Union[List[str], str, None] = None,
    name: Optional[str] = None,
    groupids: Union[List[str], str, None] = None,
    limit: Union[int, str, None] = 10
) -> str:
    """获取主机信息。支持通过ID精确查询或通过名称模糊查询。"""
    client = get_zabbix_client()
    # 参数解析、语义增强、查询执行
    ...
```

### 2. 智能参数解析

MCP Server 实现了灵活的参数解析器，支持从 Dify 传来的字符串或原生类型：

```python
def parse_list_param(value: Union[List[str], str, None]) -> Optional[List[str]]:
    """解析列表参数，支持字符串形式的JSON数组"""
    if value is None:
        return None
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass
        return [value]
    return value
```

### 3. 语义增强搜索

针对中文运维场景，实现了语义映射，将自然语言搜索词转换为 Zabbix 标准监控项关键字：

```python
semantic_map = {
    "memory": ["memory", "utilization", "available", "used", "pused"],
    "cpu": ["cpu", "utilization", "load", "interrupt"],
    "disk": ["disk", "space", "util", "used", "free"],
    "filesystem": ["fs", "space", "util"]
}
```

### 4. 时间语义解析

支持自然语言时间描述（如 "24h", "1d", "1h", "yesterday"）：

```python
def parse_semantic_time(time_val: Union[int, str, None], default_offset: int = 0) -> Optional[int]:
    """支持 Unix 时间戳或相对时间字符串"""
    if isinstance(time_val, str):
        time_val = time_val.lower().strip()
        if time_val.endswith('h'):
            hours = int(time_val.replace('h', ''))
            return int(time.time()) - (hours * 3600)
        if time_val.endswith('d'):
            days = int(time_val.replace('d', ''))
            return int(time.time()) - (days * 86400)
    ...
```

---

## 应用场景示例

### 场景1：告警查询
**用户输入**: "帮我看看 情报系统应用文件服务器 172.18.6.220 有没有报警"

**Agent处理流程**:
1. 识别到 IP 地址，调用 `get_host_by_ip(172.18.6.220)` 获取 hostid
2. 使用 hostid 调用 `problem_get` 查询当前告警
3. 按严重程度排序，生成中文报告

**输出示例**:
```
🔴 发现 3 个告警问题

严重级别 | 告警名称 | 主机 | 触发时间
---|---|---|---
🔴 高危 | CPU 使用率超过 90% | 情报系统应用文件服务器 | 2024-01-15 14:32:00
🟡 警告 | 磁盘空间不足 20% | 情报系统应用文件服务器 | 2024-01-15 13:15:00
```

### 场景2：性能趋势查询
**用户输入**: "查看 192.168.1.100 过去24小时的 CPU 趋势"

**Agent处理流程**:
1. 调用 `get_host_by_ip` 获取 hostid
2. 调用 `inspect_host_performance` 获取整体性能数据
3. 提取 CPU 相关的趋势数据

### 场景3：模糊搜索主机
**用户输入**: "帮我看看能源正式环境有没有报警"

**Agent处理流程**:
1. 无 IP 地址，调用 `host_get(name="能源正式环境")` 进行模糊匹配
2. 如返回多个结果，询问用户具体选择哪一个
3. 如返回唯一结果，直接查询告警

---

## 项目成果与价值

### 1. 运维效率提升
- **查询时间缩短**: 从登录 Zabbix Web → 导航 → 查询 的 3-5 分钟，缩短到自然语言提问的 10-30 秒
- **学习成本降低**: 无需记忆复杂的 Zabbix API 和字段名
- **中文友好**: 完整的中文交互体验，降低英文门槛

### 2. 技术创新点
| 创新点 | 说明 |
|--------|------|
| MCP 协议应用 | 国内较早将 MCP 协议应用于运维场景的案例 |
| 语义增强搜索 | 实现中文自然语言到 Zabbix 监控项的语义映射 |
| 智能参数解析 | 支持 JSON 字符串和原生类型的灵活参数处理 |
| 时间语义解析 | 支持 "24h", "1d" 等自然语言时间描述 |

### 3. 可复用性
- **MCP Server 独立可用**: 可作为标准 MCP Server 接入其他支持 MCP 的客户端
- **提示词模板化**: Dify 的提示词设计可迁移到其他类似的运维场景
- **配置化部署**: 通过环境变量和配置文件实现零代码适配不同 Zabbix 环境

---

## 后续优化方向

### 1. 功能增强
- [ ] **告警归因分析**: 基于历史告警数据训练模型，实现告警根因自动分析
- [ ] **预测性告警**: 结合趋势数据，预测未来可能的性能瓶颈
- [ ] **自动化运维**: 在只读模式之外，支持安全的自动化操作（如自动重启服务）

### 2. 多模态支持
- [ ] **图表生成**: 调用 Zabbix 的 graph API，返回监控图表
- [ ] **PDF 报告**: 自动生成每日/每周的运维报告
- [ ] **语音交互**: 支持语音输入查询，适合移动端运维场景

### 3. 生态扩展
- [ ] **Prometheus 支持**: 扩展 MCP Server 支持 Prometheus 查询
- [ ] **Kubernetes 集成**: 支持查询 K8s Pod 监控数据
- [ ] **多云管理**: 支持阿里云、腾讯云等云监控 API

---

## 附录

### A. 相关资源

| 资源 | 链接 | 说明 |
|------|------|------|
| MCP 协议文档 | https://modelcontextprotocol.io/ | 官方 MCP 协议规范 |
| FastMCP 框架 | https://github.com/jlowin/fastmcp | Python MCP 框架 |
| python-zabbix-utils | https://github.com/zabbix/python-zabbix-utils | Zabbix 官方 Python SDK |
| Dify 官网 | https://dify.ai/ | LLM 应用开发平台 |
| DeepSeek | https://deepseek.com/ | 国产大模型 |

### B. 配置文件参考

#### MCP Server 配置 (`config/mcp.json`)

```json
{
  "mcpServers": {
    "zabbix": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/path/to/zabbix-mcp-server",
        "python",
        "src/zabbix_mcp_server.py"
      ],
      "env": {
        "ZABBIX_URL": "https://zabbix.example.com",
        "ZABBIX_TOKEN": "your_api_token",
        "READ_ONLY": "true"
      }
    }
  }
}
```

#### Dify Agent 提示词

见本文档正文 **"Dify 提示词设计"** 章节。

### C. 术语表

| 术语 | 英文 | 说明 |
|------|------|------|
| MCP | Model Context Protocol | 模型上下文协议，允许大模型调用外部工具 |
| Agent | 智能体 | 能够自主决策并使用工具完成任务的 AI 系统 |
| Host | 主机 | Zabbix 中被监控的服务器或设备 |
| Item | 监控项 | Zabbix 中定义的具体监控指标 |
| Trigger | 触发器 | Zabbix 中定义的告警规则 |
| Problem | 问题 | Zabbix 中当前活跃的告警 |
| Trend | 趋势 | Zabbix 中聚合的历史数据 |

---

## 总结

本项目通过结合 **Dify** (LLM 应用平台)、**DeepSeek** (国产大模型)、**MCP 协议** (模型上下文协议) 和 **Zabbix** (企业级监控系统)，成功构建了一个智能运维助手。

该助手能够理解中文自然语言查询，自动调用 Zabbix API 获取实时数据，并以清晰的中文格式返回结果，极大地降低了运维人员使用 Zabbix 的门槛，提升了运维效率。

项目的核心技术包括 MCP Server 的开发、Dify Agent 的提示词设计、以及语义增强搜索等，这些技术具有较好的可复用性，可推广到其他类似的运维场景中。
