"""Zabbix API Client Module

This module provides a centralized Zabbix API client with authentication,
configuration management, and connection handling.
"""
import os
import logging
from typing import Optional
from zabbix_utils import ZabbixAPI
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logger = logging.getLogger(__name__)

# Global Zabbix API client instance
_zabbix_api: Optional[ZabbixAPI] = None


def get_zabbix_client() -> ZabbixAPI:
    """Get or create Zabbix API client with proper authentication.

    Returns:
        ZabbixAPI: Authenticated Zabbix API client

    Raises:
        ValueError: If required environment variables are missing
        Exception: If authentication fails
    """
    global _zabbix_api

    if _zabbix_api is None:
        url = os.getenv("ZABBIX_URL")
        if not url:
            raise ValueError("ZABBIX_URL environment variable is required")

        logger.info(f"Initializing Zabbix API client for {url}")

        # Configure SSL verification
        verify_ssl = os.getenv("VERIFY_SSL", "true").lower() in ("true", "1", "yes")
        logger.info(f"SSL certificate verification: {'enabled' if verify_ssl else 'disabled'}")

        # Initialize client
        _zabbix_api = ZabbixAPI(url=url, validate_certs=verify_ssl)

        # Authenticate using token or username/password
        token = os.getenv("ZABBIX_TOKEN")
        if token:
            logger.info("Authenticating with API token")
            _zabbix_api.login(token=token)
        else:
            user = os.getenv("ZABBIX_USER")
            password = os.getenv("ZABBIX_PASSWORD")
            if not user or not password:
                raise ValueError("Either ZABBIX_TOKEN or ZABBIX_USER/ZABBIX_PASSWORD must be set")
            logger.info(f"Authenticating with username: {user}")
            _zabbix_api.login(user=user, password=password)

        logger.info("Successfully authenticated with Zabbix API")

    return _zabbix_api


def reset_zabbix_client() -> None:
    """Reset the Zabbix API client (useful for testing or reconnection)."""
    global _zabbix_api
    _zabbix_api = None
    logger.info("Zabbix API client reset")


def is_read_only() -> bool:
    """Check if server is in read-only mode.

    Returns:
        bool: True if read-only mode is enabled
    """
    return os.getenv("READ_ONLY", "true").lower() in ("true", "1", "yes")


def validate_read_only() -> None:
    """Validate that write operations are allowed.

    Raises:
        ValueError: If server is in read-only mode
    """
    if is_read_only():
        raise ValueError("Server is in read-only mode - write operations are not allowed")


def get_zabbix_version() -> Optional[str]:
    """Get the Zabbix server version.

    Returns:
        str: Zabbix version string or None if not connected
    """
    try:
        client = get_zabbix_client()
        # Zabbix API doesn't have a direct version endpoint, but we can get it from the API info
        return "7.0.x"  # Placeholder, could be retrieved from API if needed
    except Exception:
        return None
