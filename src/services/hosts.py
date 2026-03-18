"""Host Service - Business logic for host operations."""
import logging
import re
from typing import Any, Dict, List, Optional, Union
from zabbix_utils import ZabbixAPI

logger = logging.getLogger(__name__)


class HostService:
    """Service class for host-related operations."""

    def __init__(self, client: ZabbixAPI):
        self.client = client

    def get_host_by_id(self, hostid: str) -> Optional[Dict[str, Any]]:
        """Get host by ID."""
        result = self.client.host.get(
            hostids=[hostid],
            output=["hostid", "host", "name", "status", "available"],
            selectInterfaces=["ip", "dns", "available", "error", "type"]
        )
        return result[0] if result else None

    def get_hosts(
        self,
        hostids: Optional[List[str]] = None,
        name: Optional[str] = None,
        groupids: Optional[List[str]] = None,
        templateids: Optional[List[str]] = None,
        output: Optional[List[str]] = None,
        search: Optional[Dict[str, str]] = None,
        filter_params: Optional[Dict[str, Any]] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get hosts with flexible filtering."""
        if output is None:
            output = ["hostid", "host", "name", "status", "available"]

        params: Dict[str, Any] = {
            "output": output,
            "limit": limit,
            "searchWildcardsEnabled": True,
            "searchByAny": True
        }

        if hostids:
            params["hostids"] = hostids
        if groupids:
            params["groupids"] = groupids
        if templateids:
            params["templateids"] = templateids
        if search:
            params["search"] = search
        if filter_params:
            params["filter"] = filter_params
        if name:
            params["search"] = {"name": f"*{name}*"}

        return self.client.host.get(**params)

    def resolve_host_identifier(self, identifier: str) -> Optional[str]:
        """Resolve host identifier (IP, hostname, or hostid) to hostid.

        Args:
            identifier: IP address, hostname, or hostid

        Returns:
            hostid or None if not found
        """
        # Try direct hostid first
        if identifier.isdigit():
            result = self.client.host.get(
                hostids=[identifier],
                output=["hostid"]
            )
            if result:
                return result[0]["hostid"]

        # Try exact hostname match
        result = self.client.host.get(
            filter={"host": identifier},
            output=["hostid"]
        )
        if result:
            return result[0]["hostid"]

        # Try name match
        result = self.client.host.get(
            search={"name": identifier},
            searchWildcardsEnabled=True,
            output=["hostid"]
        )
        if result:
            return result[0]["hostid"]

        # Try IP address match
        result = self.client.host.get(
            selectInterfaces=["ip"],
            output=["hostid"]
        )
        for host in result:
            for interface in host.get("interfaces", []):
                if interface.get("ip") == identifier:
                    return host["hostid"]

        return None

    def get_host_summary(self) -> Dict[str, int]:
        """Get summary statistics for all hosts."""
        hosts = self.client.host.get(
            output=["hostid", "available", "status"],
            selectInterfaces=["type"]
        )

        total = len(hosts)
        enabled = sum(1 for h in hosts if h.get("status") == "0")
        disabled = sum(1 for h in hosts if h.get("status") == "1")
        available = sum(1 for h in hosts if h.get("available") == "1")
        unavailable = sum(1 for h in hosts if h.get("available") == "2")
        unknown = sum(1 for h in hosts if h.get("available") == "0")

        return {
            "total": total,
            "enabled": enabled,
            "disabled": disabled,
            "available": available,
            "unavailable": unavailable,
            "unknown": unknown
        }

    def get_host_items(
        self,
        hostid: str,
        key_patterns: Optional[List[str]] = None,
        output: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Get items for a host, optionally filtered by key patterns."""
        if output is None:
            output = ["itemid", "name", "key_", "lastvalue", "units", "value_type"]

        params: Dict[str, Any] = {
            "hostids": hostid,
            "output": output,
            "filter": {"status": 0}
        }

        items = self.client.item.get(**params)

        if key_patterns:
            filtered = []
            for item in items:
                key = item.get("key_", "").lower()
                for pattern in key_patterns:
                    if pattern.lower() in key:
                        filtered.append(item)
                        break
            return filtered

        return items

    def find_items_by_key_patterns(
        self,
        hostid: str,
        patterns: List[str],
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Find items matching key patterns."""
        items = self.get_host_items(hostid)
        results = []

        for item in items:
            key = item.get("key_", "").lower()
            for pattern in patterns:
                if pattern.lower() in key:
                    results.append(item)
                    if len(results) >= limit:
                        return results
                    break

        return results
