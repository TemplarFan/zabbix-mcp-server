"""Server Module - MCP Server initialization and configuration."""
import os
import logging
from typing import Optional
from fastmcp import FastMCP

logger = logging.getLogger(__name__)


def create_mcp_server(name: str = "Zabbix MCP Server") -> FastMCP:
    """Create and configure the MCP server.

    Args:
        name: Server name

    Returns:
        Configured FastMCP instance
    """
    mcp = FastMCP(name)
    return mcp


def get_transport_config() -> dict:
    """Get transport configuration from environment.

    Returns:
        Dictionary with transport settings
    """
    transport = os.getenv("ZABBIX_MCP_TRANSPORT", "stdio")

    config = {
        "transport": transport,
        "host": os.getenv("ZABBIX_MCP_HOST", "127.0.0.1"),
        "port": int(os.getenv("ZABBIX_MCP_PORT", "8000")),
    }

    return config


def run_server(mcp: FastMCP, config: Optional[dict] = None) -> None:
    """Run the MCP server with the given configuration.

    Args:
        mcp: FastMCP instance
        config: Optional configuration dictionary
    """
    if config is None:
        config = get_transport_config()

    transport = config.get("transport", "stdio")
    logger.info(f"Starting Zabbix MCP Server with transport: {transport}")

    if transport == "stdio":
        mcp.run(transport="stdio")
    elif transport == "streamable-http":
        host = config.get("host", "127.0.0.1")
        port = config.get("port", 8000)
        mcp.run(transport="streamable-http", host=host, port=port)
    else:
        raise ValueError(f"Unknown transport: {transport}")
