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
mcp.tool()(host_get)
mcp.tool()(hostgroup_get)
mcp.tool()(hostgroup_get_hosts)
mcp.tool()(host_software_inventory_get)
mcp.tool()(host_update)

# Register item tools
mcp.tool()(item_get)

# Register trigger tools
mcp.tool()(trigger_get)

# Register event tools
mcp.tool()(event_get)

# Register history tools
mcp.tool()(history_get)

# Register summary tools
mcp.tool()(get_problem_summary)
mcp.tool()(get_problem_fact_detail)
mcp.tool()(check_host_health)
mcp.tool()(quick_status)
mcp.tool()(host_alert_history)

# Register trend tools
mcp.tool()(trend_get)
mcp.tool()(trend_summary)

# Register report tools
mcp.tool()(event_daily_report)
mcp.tool()(event_weekly_report)
mcp.tool()(event_monthly_report)

# Register system tools
mcp.tool()(apiinfo_version)
mcp.tool()(get_host_by_ip)


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
        mcp.run(
            transport="streamable-http",
            host=host,
            port=port,
            stateless_http=stateless,
        )
    else:
        logger.error(f"Unknown transport: {transport}")
        sys.exit(1)


if __name__ == "__main__":
    main()
