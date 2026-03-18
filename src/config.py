"""Configuration Module - Centralized configuration management."""
import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class ZabbixConfig:
    """Zabbix connection configuration."""
    url: str
    token: Optional[str] = None
    user: Optional[str] = None
    password: Optional[str] = None
    verify_ssl: bool = True

    @classmethod
    def from_env(cls) -> "ZabbixConfig":
        """Create configuration from environment variables."""
        url = os.getenv("ZABBIX_URL", "")
        token = os.getenv("ZABBIX_TOKEN")
        user = os.getenv("ZABBIX_USER")
        password = os.getenv("ZABBIX_PASSWORD")
        verify_ssl = os.getenv("VERIFY_SSL", "true").lower() in ("true", "1", "yes")

        return cls(
            url=url,
            token=token,
            user=user,
            password=password,
            verify_ssl=verify_ssl
        )

    def validate(self) -> None:
        """Validate the configuration.

        Raises:
            ValueError: If configuration is invalid
        """
        if not self.url:
            raise ValueError("ZABBIX_URL environment variable is required")

        if not self.token and (not self.user or not self.password):
            raise ValueError(
                "Either ZABBIX_TOKEN or ZABBIX_USER/ZABBIX_PASSWORD must be set"
            )


@dataclass
class ServerConfig:
    """MCP Server configuration."""
    read_only: bool = True
    transport: str = "stdio"
    host: str = "127.0.0.1"
    port: int = 8000
    debug: bool = False

    @classmethod
    def from_env(cls) -> "ServerConfig":
        """Create configuration from environment variables."""
        return cls(
            read_only=os.getenv("READ_ONLY", "true").lower() in ("true", "1", "yes"),
            transport=os.getenv("ZABBIX_MCP_TRANSPORT", "stdio"),
            host=os.getenv("ZABBIX_MCP_HOST", "127.0.0.1"),
            port=int(os.getenv("ZABBIX_MCP_PORT", "8000")),
            debug=os.getenv("DEBUG", "false").lower() in ("true", "1", "yes")
        )


@dataclass
class AppConfig:
    """Application configuration."""
    zabbix: ZabbixConfig
    server: ServerConfig

    @classmethod
    def from_env(cls) -> "AppConfig":
        """Create configuration from environment variables."""
        return cls(
            zabbix=ZabbixConfig.from_env(),
            server=ServerConfig.from_env()
        )

    def validate(self) -> None:
        """Validate all configuration."""
        self.zabbix.validate()
