# Zabbix MCP Server

[English](README.md) | 中文文档

[![License: GPL-3.0](https://img.shields.io/badge/License-GPL--3.0-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

基于 FastMCP 与 python-zabbix-utils 的 Zabbix Model Context Protocol（MCP）服务器。内置 21 个聚焦工具，覆盖主机、监控项、触发器、问题与监控数据查询，并附带日/周/月运维报表生成器——面向 AI 辅助运维（AIOps）智能体设计。

## 功能特性

### 🏠 主机管理
- `host_get` - 查询主机，支持过滤、群组/模板选择与资产信息
- `host_update` - 修改主机可见名称与所属群组
- `get_host_by_ip` - 通过 IP 精确定位主机
- `hostgroup_get` - 查询主机组
- `hostgroup_get_hosts` - 列出一个或多个主机组内的主机
- `host_software_inventory_get` - 查询单台主机的软件资产

### 📊 监控数据
- `item_get` - 查询监控项，支持语义搜索与关键指标筛选
- `trigger_get` - 查询触发器，可按严重级别过滤
- `history_get` - 获取监控项原始历史数据
- `trend_get` - 获取小时聚合趋势数据
- `trend_summary` - 时间窗口内按样本数加权汇总的趋势摘要

### 🚨 问题与事件
- `event_get` - 游标分页查询原始历史事件
- `get_problem_summary` - 当前问题的统一分类摘要
- `get_problem_fact_detail` - 每条问题事件的真实恢复、人工处置与当前监控状态
- `quick_status` - 整体状态：主机、分类问题与最近 24 小时事件
- `check_host_health` - 单主机接口可用性、问题分类与关键指标
- `host_alert_history` - 按主机和触发器的完整告警/恢复配对历史

### 📈 运维报表
- `event_daily_report` - 生成 Markdown 运维日报
- `event_weekly_report` - 生成运维周报（周一至周日）
- `event_monthly_report` - 生成运维月报

### ℹ️ 系统
- `apiinfo_version` - 获取 Zabbix API 版本

## 安装

### 前置要求

- Python 3.10 或更高版本
- [uv](https://docs.astral.sh/uv/) 包管理器
- 可访问的、已启用 API 的 Zabbix 服务器

### 快速开始

1. **克隆仓库：**
   ```bash
   git clone https://github.com/TemplarFan/zabbix-mcp-server.git
   cd zabbix-mcp-server
   ```

2. **安装依赖：**
   ```bash
   uv sync
   ```

3. **配置环境变量：**
   ```bash
   cp config/.env.example .env
   # 编辑 .env，填入你的 Zabbix 服务器信息
   ```

4. **验证安装：**
   ```bash
   uv run python scripts/test_server.py
   ```

## 配置

### 必填环境变量

- `ZABBIX_URL` - Zabbix 服务器 API 端点（如 `https://zabbix.example.com`）

### 认证方式（二选一）

**方式一：API Token（推荐）**
- `ZABBIX_TOKEN` - 你的 Zabbix API Token

**方式二：用户名/密码**
- `ZABBIX_USER` - Zabbix 用户名
- `ZABBIX_PASSWORD` - Zabbix 密码

### 可选配置

- `READ_ONLY` - 设为 `true`、`1` 或 `yes` 启用只读模式（仅允许查询操作）
- `VERIFY_SSL` - 启用/禁用 SSL 证书校验（默认：`true`）
- `ZABBIX_TEST_NETWORKS` - 逗号分隔的测试网段 CIDR（如 `192.168.100.0/24,192.168.101.0/24`），报表工具在 `production_only=true` 时排除这些网段的主机；留空则不排除

### 传输方式配置

- `ZABBIX_MCP_TRANSPORT` - 传输类型：`stdio`（默认）或 `streamable-http`

**HTTP 传输配置**（仅在 `ZABBIX_MCP_TRANSPORT=streamable-http` 时使用）：
- `ZABBIX_MCP_HOST` - 服务监听地址（默认：`127.0.0.1`）
- `ZABBIX_MCP_PORT` - 服务端口（默认：`8000`）
- `ZABBIX_MCP_STATELESS_HTTP` - 无状态模式（默认：`false`）
- `AUTH_TYPE` - streamable-http 传输必须设为 `no-auth`

## 使用

### 启动服务

**使用启动脚本（推荐）：**
```bash
uv run python scripts/start_server.py
```

**直接运行：**
```bash
uv run python -m src.main
```

### 传输方式

服务支持两种传输方式：

#### STDIO 传输（默认）
标准输入输出传输，适用于 Claude Desktop 等 MCP 客户端：
```bash
# 在 .env 或环境变量中设置
ZABBIX_MCP_TRANSPORT=stdio
```

#### HTTP 传输
基于 HTTP 的传输，适用于 Web 集成：
```bash
# 在 .env 或环境变量中设置
ZABBIX_MCP_TRANSPORT=streamable-http
ZABBIX_MCP_HOST=127.0.0.1
ZABBIX_MCP_PORT=8000
ZABBIX_MCP_STATELESS_HTTP=false
AUTH_TYPE=no-auth
```

**注意：** 使用 `streamable-http` 传输时，`AUTH_TYPE` 必须设为 `no-auth`。

### 测试

**运行测试：**
```bash
uv run python scripts/test_server.py
```

### 只读模式

设置 `READ_ONLY=true` 后，服务只暴露查询操作，阻止所有创建、修改、删除操作。适用于：

- 📊 监控大盘
- 🔍 只读集成场景
- 🔒 安全敏感环境
- 🛡️ 防止误操作

### 工具调用示例

**查询所有主机：**
```python
host_get()
```

**查询指定群组的主机：**
```python
host_get(groupids=["1"])
```

**汇总当前需处理的问题：**
```python
get_problem_summary(view="actionable")
```

**查询历史数据：**
```python
history_get(
    itemids=["12345"],
    time_from="24h",
    limit=100
)
```

**检查主机健康：**
```python
check_host_health(host_identifier="web-server-01")
```

**生成昨日运维日报：**
```python
event_daily_report(date="yesterday", production_only=true)
```

## MCP 集成

本服务适配 Claude Desktop 等支持 MCP 的客户端。详细接入步骤见 [MCP_SETUP.md](MCP_SETUP.md)。

## 开发

### 项目结构

```
zabbix-mcp-server/
├── src/                        # MCP 服务实现
│   ├── main.py                 # 服务入口与工具注册
│   ├── client.py               # Zabbix API 客户端
│   ├── config.py               # 可配置参数
│   ├── tools/                  # MCP 工具定义
│   ├── reporting/              # 日/周/月报表生成器
│   ├── services/               # 业务逻辑服务
│   └── utils/                  # 工具函数
├── scripts/
│   ├── start_server.py         # 带校验的启动脚本
│   └── test_server.py          # 测试脚本
├── config/
│   ├── .env.example            # 环境配置模板
│   ├── mcp.json                # MCP 客户端配置示例
│   ├── prompt.md               # Agent 系统提示词模板
│   └── workflow_prompt.md      # 告警分析工作流提示词
├── .env.example                # 环境配置模板
├── pyproject.toml              # Python 项目配置
├── requirements.txt            # 依赖清单
├── uv.lock                     # 锁定文件，保证可复现安装
├── README.md                   # 英文说明
├── README.zh-CN.md             # 中文说明（本文件）
├── MCP_SETUP.md                # MCP 接入指南
└── LICENSE                     # GPL-3.0 许可证
```

### 参与贡献

1. Fork 本仓库
2. 创建功能分支（`git checkout -b feature/amazing-feature`）
3. 提交改动（`git commit -m 'Add amazing feature'`）
4. 推送分支（`git push origin feature/amazing-feature`）
5. 发起 Pull Request

### 运行测试

```bash
# 测试服务功能
uv run python scripts/test_server.py
```

## 错误处理

服务内置完善的错误处理：

- ✅ 认证错误清晰上报
- 🔒 只读模式违规操作被阻止并给出明确提示
- ✔️ 无效参数自动校验
- 🌐 网络与 API 错误规范化输出
- 📝 详尽日志便于排查

## 安全建议

- 🔑 优先使用 API Token，而非用户名/密码
- 🔒 纯监控场景启用只读模式
- 🛡️ 妥善保管环境变量
- 🔐 Zabbix 连接使用 HTTPS
- 🔄 定期轮换 API Token
- 📁 配置文件安全存放

## 故障排查

### 常见问题

**连接失败：**
- 确认 `ZABBIX_URL` 正确且可访问
- 检查认证凭证
- 确认 Zabbix API 已启用

**权限不足：**
- 确认用户具备足够的 Zabbix 权限
- 修改数据时检查是否开启了只读模式

**工具未找到：**
- 确认依赖已全部安装：`uv sync`
- 确认 Python 版本（3.10+）

### 调试模式

设置环境变量开启详细日志：
```bash
export DEBUG=1
uv run python scripts/start_server.py
```

## 依赖

- [FastMCP](https://github.com/jlowin/fastmcp) - MCP 服务框架
- [python-zabbix-utils](https://github.com/zabbix/python-zabbix-utils) - Zabbix 官方 Python 库

## 许可证

本项目基于 GNU General Public License v3.0 发布，详见 [LICENSE](LICENSE)。

## 项目沿革

基于 [mpeirone/zabbix-mcp-server](https://github.com/mpeirone/zabbix-mcp-server)（GPL-3.0）大幅重写并扩展：

- 运维报表生成器（日/周/月），内置统一问题分类
- 问题事实核查服务（真实恢复与人工处置状态）
- 由环境配置驱动的生产口径过滤
- 面向 Dify 助手与 n8n 工作流的告警分析提示词模板
- 与实际实现完全对齐、文档完备的 21 个 MCP 工具

## 致谢

- [Zabbix](https://www.zabbix.com/) - 监控平台
- [Model Context Protocol](https://modelcontextprotocol.io/) - 集成标准
- [FastMCP](https://github.com/jlowin/fastmcp) - 服务框架

---

**为 Zabbix 与 MCP 社区用心打造 ❤️**
