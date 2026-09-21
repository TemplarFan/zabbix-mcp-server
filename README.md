# Zabbix MCP Server

[![License: GPL-3.0](https://img.shields.io/badge/License-GPL--3.0-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

A Model Context Protocol (MCP) server for Zabbix integration using FastMCP and python-zabbix-utils. It ships 21 focused tools for querying hosts, items, triggers, problems and monitoring data, plus daily/weekly/monthly operations report generators — designed for AI-assisted operations (AIOps) agents.

## Features

### 🏠 Host Management
- `host_get` - Query hosts with filtering, group/template selection and inventory
- `host_update` - Update a host's visible name and host groups
- `get_host_by_ip` - Look up a host precisely by its IP address
- `hostgroup_get` - Query host groups
- `hostgroup_get_hosts` - List hosts inside one or more host groups
- `host_software_inventory_get` - Query a single host's software inventory

### 📊 Monitoring Data
- `item_get` - Query items with semantic search and key-metric filtering
- `trigger_get` - Query triggers, optionally filtered by severity
- `history_get` - Get raw item history data
- `trend_get` - Get hourly-aggregated trend data
- `trend_summary` - Sample-weighted trend summary over a time window

### 🚨 Problems & Events
- `event_get` - Query raw historical events with cursor pagination
- `get_problem_summary` - Unified classification summary of current problems
- `get_problem_fact_detail` - Real recovery, manual handling and current monitoring status per problem event
- `quick_status` - Overall status: hosts, classified problems and last-24h events
- `check_host_health` - Per-host interface availability, problem classification and key metrics
- `host_alert_history` - Fully paired alert/recovery history per host and trigger

### 📈 Operations Reports
- `event_daily_report` - Generate a daily operations report in Markdown
- `event_weekly_report` - Generate a weekly (Mon–Sun) operations report
- `event_monthly_report` - Generate a monthly operations report

### ℹ️ System
- `apiinfo_version` - Get the Zabbix API version

## Installation

### Prerequisites

- Python 3.10 or higher
- [uv](https://docs.astral.sh/uv/) package manager
- Access to a Zabbix server with API enabled

### Quick Start

1. **Clone the repository:**
   ```bash
   git clone https://github.com/TemplarFan/zabbix-mcp-server.git
   cd zabbix-mcp-server
   ```

2. **Install dependencies:**
   ```bash
   uv sync
   ```

3. **Configure environment variables:**
   ```bash
   cp config/.env.example .env
   # Edit .env with your Zabbix server details
   ```

4. **Test the installation:**
   ```bash
   uv run python scripts/test_server.py
   ```

## Configuration

### Required Environment Variables

- `ZABBIX_URL` - Your Zabbix server API endpoint (e.g., `https://zabbix.example.com`)

### Authentication (choose one method)

**Method 1: API Token (Recommended)**
- `ZABBIX_TOKEN` - Your Zabbix API token

**Method 2: Username/Password**
- `ZABBIX_USER` - Your Zabbix username
- `ZABBIX_PASSWORD` - Your Zabbix password

### Optional Configuration

- `READ_ONLY` - Set to `true`, `1`, or `yes` to enable read-only mode (only GET operations allowed)
- `VERIFY_SSL` - Enable/disable SSL certificate verification (default: `true`)
- `ZABBIX_TEST_NETWORKS` - Comma-separated test network CIDRs (e.g., `192.168.100.0/24,192.168.101.0/24`) excluded by report tools when `production_only=true`; leave empty to disable

### Transport Configuration

- `ZABBIX_MCP_TRANSPORT` - Transport type: `stdio` (default) or `streamable-http`

**HTTP Transport Configuration** (only used when `ZABBIX_MCP_TRANSPORT=streamable-http`):
- `ZABBIX_MCP_HOST` - Server host (default: `127.0.0.1`)
- `ZABBIX_MCP_PORT` - Server port (default: `8000`)
- `ZABBIX_MCP_STATELESS_HTTP` - Stateless mode (default: `false`)
- `AUTH_TYPE` - Must be set to `no-auth` for streamable-http transport

## Usage

### Running the Server

**With startup script (recommended):**
```bash
uv run python scripts/start_server.py
```

**Direct execution:**
```bash
uv run python src/zabbix_mcp_server.py
```

### Transport Options

The server supports two transport methods:

#### STDIO Transport (Default)
Standard input/output transport for MCP clients like Claude Desktop:
```bash
# Set in .env or environment
ZABBIX_MCP_TRANSPORT=stdio
```

#### HTTP Transport
HTTP-based transport for web integrations:
```bash
# Set in .env or environment
ZABBIX_MCP_TRANSPORT=streamable-http
ZABBIX_MCP_HOST=127.0.0.1
ZABBIX_MCP_PORT=8000
ZABBIX_MCP_STATELESS_HTTP=false
AUTH_TYPE=no-auth
```

**Note:** When using `streamable-http` transport, `AUTH_TYPE` must be set to `no-auth`.

### Testing

**Run test suite:**
```bash
uv run python scripts/test_server.py
```

### Read-Only Mode

When `READ_ONLY=true`, the server will only expose GET operations (retrieve data) and block all create, update, and delete operations. This is useful for:

- 📊 Monitoring dashboards
- 🔍 Read-only integrations
- 🔒 Security-conscious environments
- 🛡️ Preventing accidental modifications

### Example Tool Calls

**Get all hosts:**
```python
host_get()
```

**Get hosts in specific group:**
```python
host_get(groupids=["1"])
```

**Summarize current problems needing attention:**
```python
get_problem_summary(view="actionable")
```

**Get history data:**
```python
history_get(
    itemids=["12345"],
    time_from="24h",
    limit=100
)
```

**Check a host's health:**
```python
check_host_health(host_identifier="web-server-01")
```

**Generate yesterday's operations report:**
```python
event_daily_report(date="yesterday", production_only=true)
```

## MCP Integration

This server is designed to work with MCP-compatible clients like Claude Desktop. See [MCP_SETUP.md](MCP_SETUP.md) for detailed integration instructions.

## Development

### Project Structure

```
zabbix-mcp-server/
├── src/                        # MCP server implementation
│   ├── main.py                 # Server entrypoint and tool registration
│   ├── client.py               # Zabbix API client
│   ├── config.py               # Configurable parameters
│   ├── tools/                  # MCP tool definitions
│   ├── reporting/              # Daily/weekly/monthly report generators
│   ├── services/               # Business logic services
│   └── utils/                  # Helpers
├── scripts/
│   ├── start_server.py         # Startup script with validation
│   └── test_server.py          # Test script
├── config/
│   ├── .env.example            # Environment configuration template
│   ├── mcp.json                # MCP client configuration example
│   ├── prompt.md               # Agent system prompt template
│   └── workflow_prompt.md      # Alarm analysis workflow prompt
├── .env.example                # Environment configuration template
├── pyproject.toml              # Python project configuration
├── requirements.txt            # Dependencies
├── uv.lock                     # Lockfile for reproducible installs
├── README.md                   # This file
├── MCP_SETUP.md                # MCP integration guide
└── LICENSE                     # GPL-3.0 license
```

### Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

### Running Tests

```bash
# Test server functionality
uv run python scripts/test_server.py
```

## Error Handling

The server includes comprehensive error handling:

- ✅ Authentication errors are clearly reported
- 🔒 Read-only mode violations are blocked with descriptive messages
- ✔️ Invalid parameters are validated
- 🌐 Network and API errors are properly formatted
- 📝 Detailed logging for troubleshooting

## Security Considerations

- 🔑 Use API tokens instead of username/password when possible
- 🔒 Enable read-only mode for monitoring-only use cases
- 🛡️ Secure your environment variables
- 🔐 Use HTTPS for Zabbix server connections
- 🔄 Regularly rotate API tokens
- 📁 Store configuration files securely

## Troubleshooting

### Common Issues

**Connection Failed:**
- Verify `ZABBIX_URL` is correct and accessible
- Check authentication credentials
- Ensure Zabbix API is enabled

**Permission Denied:**
- Verify user has sufficient Zabbix permissions
- Check if read-only mode is enabled when trying to modify data

**Tool Not Found:**
- Ensure all dependencies are installed: `uv sync`
- Verify Python version compatibility (3.10+)

### Debug Mode

Set environment variable for detailed logging:
```bash
export DEBUG=1
uv run python scripts/start_server.py
```

## Dependencies

- [FastMCP](https://github.com/jlowin/fastmcp) - MCP server framework
- [python-zabbix-utils](https://github.com/zabbix/python-zabbix-utils) - Official Zabbix Python library

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

## Project Origin

Based on [mpeirone/zabbix-mcp-server](https://github.com/mpeirone/zabbix-mcp-server) (GPL-3.0). This project has been substantially rewritten and extended with:

- Operations report generators (daily / weekly / monthly) with unified problem classification
- Problem fact-checking service (true recovery and manual handling status)
- Production-only filtering driven by environment configuration
- Alarm-analysis prompt templates for Dify assistants and n8n workflows
- A fully documented 21-tool MCP toolset aligned with the actual implementation

## Acknowledgments

- [Zabbix](https://www.zabbix.com/) for the monitoring platform
- [Model Context Protocol](https://modelcontextprotocol.io/) for the integration standard
- [FastMCP](https://github.com/jlowin/fastmcp) for the server framework

---

**Made with ❤️ for the Zabbix and MCP communities**