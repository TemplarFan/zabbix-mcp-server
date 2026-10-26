"""Zabbix MCP Server - Main Entry Point

This is the main entry point for the Zabbix MCP Server.
It initializes the MCP server and registers all tools.
"""
import os
import sys
import logging
from dotenv import load_dotenv

# Add src to path
sys.path.insert(0, os.path.dirname(__file__))

from fastmcp import FastMCP

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO if os.getenv("DEBUG") else logging.WARNING,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Initialize FastMCP
mcp = FastMCP("Zabbix MCP Server")

# Import and register tools
from tools import (
    # Host tools
    host_get,
    hostgroup_get,
    hostgroup_get_hosts,
    host_software_inventory_get,
    host_update,
    # Item tools
    item_get,
    # Trigger tools
    trigger_get,
    # Event tools
    event_get,
    # History tools
    history_get,
    # Summary tools
    get_problem_summary,
    get_problem_fact_detail,
    check_host_health,
    quick_status,
    host_alert_history,
    # Trend tools
    trend_get,
    trend_summary,
    # Report tools
    event_daily_report,
    event_weekly_report,
    event_monthly_report,
    # System tools
    apiinfo_version,
    get_host_by_ip,
)

# Register host tools
from config import DENIED_TOOLS_ENV, get_denied_tools

_registered_tools: list[str] = []
_attempted_tool_names: set[str] = set()


def _register(tool_fn):
    """注册工具；出现在 ZABBIX_DENY_TOOLS 中的工具跳过注册（模型不可见）。"""
    name = tool_fn.__name__
    _attempted_tool_names.add(name)
    if name in get_denied_tools():
        logger.warning("工具 %s 已被 %s 禁用，跳过注册", name, DENIED_TOOLS_ENV)
        return
    mcp.tool()(tool_fn)
    _registered_tools.append(name)


_register(host_get)
_register(hostgroup_get)
_register(hostgroup_get_hosts)
_register(host_software_inventory_get)
_register(host_update)

# Register item tools
_register(item_get)

# Register trigger tools
_register(trigger_get)

# Register event tools
_register(event_get)

# Register history tools
_register(history_get)

# Register summary tools
_register(get_problem_summary)
_register(get_problem_fact_detail)
_register(check_host_health)
_register(quick_status)
_register(host_alert_history)

# Register trend tools
_register(trend_get)
_register(trend_summary)

# Register report tools
_register(event_daily_report)
_register(event_weekly_report)
_register(event_monthly_report)

# Register system tools
_register(apiinfo_version)
_register(get_host_by_ip)

_unknown_denied = set(get_denied_tools()) - _attempted_tool_names
if _unknown_denied:
    logger.warning("%s 含未知工具名（未匹配任何已注册工具）: %s",
                   DENIED_TOOLS_ENV, ", ".join(sorted(_unknown_denied)))


def main():
    """Run the MCP server."""
    transport = os.getenv("ZABBIX_MCP_TRANSPORT", "stdio")
    host = os.getenv("ZABBIX_MCP_HOST", "127.0.0.1")
    port = int(os.getenv("ZABBIX_MCP_PORT", "8000"))
    stateless = os.getenv("ZABBIX_MCP_STATELESS_HTTP", "false").lower() in ("true", "1", "yes")

    logger.info(
        f"Starting Zabbix MCP Server with transport: {transport}, stateless: {stateless}"
    )

    if transport == "stdio":
        mcp.run(transport="stdio")
    elif transport == "streamable-http":
        # 自建 Starlette 应用以挂载 IP 白名单中间件；stdio 无网络面不经过此路径。
        # uvicorn 参数对齐 fastmcp 内部 run 的取值（lifespan/on、无优雅停机等待）。
        from ip_filter import IPFilterMiddleware

        app = mcp.http_app(transport="streamable-http", stateless_http=stateless)
        app.add_middleware(IPFilterMiddleware)

        import uvicorn
        config = uvicorn.Config(
            app, host=host, port=port,
            lifespan="on", timeout_graceful_shutdown=0, log_level="info",
        )
        uvicorn.Server(config).run()
    else:
        logger.error(f"Unknown transport: {transport}")
        sys.exit(1)


if __name__ == "__main__":
    main()
