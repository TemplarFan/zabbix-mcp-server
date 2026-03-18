"""Zabbix MCP Server - Main Entry Point

This is the main entry point for the Zabbix MCP Server.
It initializes the MCP server and registers all tools.
"""
import os
import sys
import logging
from dotenv import load_dotenv

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

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
    # Item tools
    item_get,
    # Trigger tools
    trigger_get,
    # Problem tools
    problem_get,
    event_get,
    # History tools
    history_get,
    # Summary tools
    get_problem_summary,
    check_host_health,
    quick_status,
    # Trend tools
    trend_get,
    trend_summary,
    # System tools
    apiinfo_version,
    get_host_by_ip,
)

# Register host tools
mcp.tool()(host_get)

# Register item tools
mcp.tool()(item_get)

# Register trigger tools
mcp.tool()(trigger_get)

# Register problem tools
mcp.tool()(problem_get)
mcp.tool()(event_get)

# Register history tools
mcp.tool()(history_get)

# Register summary tools
mcp.tool()(get_problem_summary)
mcp.tool()(check_host_health)
mcp.tool()(quick_status)

# Register trend tools
mcp.tool()(trend_get)
mcp.tool()(trend_summary)

# Register system tools
mcp.tool()(apiinfo_version)
mcp.tool()(get_host_by_ip)


def main():
    """Run the MCP server."""
    transport = os.getenv("ZABBIX_MCP_TRANSPORT", "stdio")
    host = os.getenv("ZABBIX_MCP_HOST", "127.0.0.1")
    port = int(os.getenv("ZABBIX_MCP_PORT", "8000"))

    logger.info(f"Starting Zabbix MCP Server with transport: {transport}")

    if transport == "stdio":
        mcp.run(transport="stdio")
    elif transport == "streamable-http":
        mcp.run(transport="streamable-http", host=host, port=port)
    else:
        logger.error(f"Unknown transport: {transport}")
        sys.exit(1)


if __name__ == "__main__":
    main()
