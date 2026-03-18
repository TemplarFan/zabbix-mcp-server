"""Summary Service - Data aggregation and formatting for summary views."""
import logging
import time
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
from zabbix_utils import ZabbixAPI

from .hosts import HostService
from .problems import ProblemService

logger = logging.getLogger(__name__)


class SummaryService:
    """Service class for generating summary reports."""

    def __init__(self, client: ZabbixAPI):
        self.client = client
        self.host_service = HostService(client)
        self.problem_service = ProblemService(client)

    def get_overall_status(self) -> Dict[str, Any]:
        """Get overall Zabbix status summary."""
        # Host statistics
        host_stats = self.host_service.get_host_summary()

        # Problem statistics (last 24 hours)
        now = int(time.time())
        time_from = now - 24 * 3600
        problem_counts = self.problem_service.count_problems_by_severity(time_from=time_from)
        total_problems = sum(problem_counts.values())

        return {
            "hosts": host_stats,
            "problems": {
                "total": total_problems,
                "by_severity": problem_counts
            },
            "timestamp": now
        }

    def get_host_health_data(
        self,
        hostid: str,
        time_range: str = "24h",
        include_trends: bool = False,
        trend_hours: int = 24
    ) -> Dict[str, Any]:
        """Get comprehensive health data for a host."""
        # Get host info
        host = self.host_service.get_host_by_id(hostid)
        if not host:
            return {"error": f"Host not found: {hostid}"}

        # Parse time range
        now = int(time.time())
        time_from = self._parse_time_range(time_range, now)

        # Get problems
        problems = self.problem_service.get_host_problems(hostid, time_from=time_from)

        # Get key metrics
        cpu_items = self.host_service.find_items_by_key_patterns(
            hostid, ["system.cpu.util"], limit=1
        )
        memory_items = self.host_service.find_items_by_key_patterns(
            hostid, ["vm.memory.util"], limit=1
        )
        disk_items = self.host_service.find_items_by_key_patterns(
            hostid, ["vfs.fs.size[pused", "disk.utilization"], limit=1
        )
        fs_items = self.host_service.find_items_by_key_patterns(
            hostid, ["vfs.fs.size"], limit=3
        )

        # Get trends if requested
        trends_data = {}
        if include_trends:
            for key, items in [
                ("cpu", cpu_items),
                ("memory", memory_items)
            ]:
                if items:
                    trends = self.client.trend.get(
                        itemids=items[0]["itemid"],
                        time_from=now - trend_hours * 3600,
                        time_till=now,
                        output=["clock", "value_avg", "value_max", "value_min"]
                    )
                    trends_data[key] = trends

        return {
            "host": host,
            "problems": problems,
            "metrics": {
                "cpu": cpu_items,
                "memory": memory_items,
                "disk": disk_items,
                "filesystem": fs_items
            },
            "trends": trends_data if include_trends else None,
            "timestamp": now
        }

    def calculate_trend_summary(
        self,
        trends: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Calculate summary statistics from trend data."""
        if not trends:
            return {}

        values_avg = [t.get("value_avg", 0) for t in trends if t.get("value_avg") is not None]
        values_max = [t.get("value_max", 0) for t in trends if t.get("value_max") is not None]
        values_min = [t.get("value_min", 0) for t in trends if t.get("value_min") is not None]

        if not values_avg:
            return {}

        current = values_avg[-1]
        avg = sum(values_avg) / len(values_avg)
        max_val = max(values_max) if values_max else 0
        min_val = min(values_min) if values_min else 0

        # Find peak time
        peak_idx = values_max.index(max_val) if values_max else 0
        peak_time = trends[peak_idx].get("clock") if peak_idx < len(trends) else None

        # Calculate trend direction
        mid = len(values_avg) // 2
        if mid > 0:
            first_half = sum(values_avg[:mid]) / mid
            second_half = sum(values_avg[mid:]) / (len(values_avg) - mid)

            if second_half > first_half * 1.1:
                trend_direction = "⬆️ 上升"
            elif second_half < first_half * 0.9:
                trend_direction = "⬇️ 下降"
            else:
                trend_direction = "➡️ 平稳"
        else:
            trend_direction = "➡️ 平稳"

        return {
            "current": current,
            "avg": avg,
            "max": max_val,
            "min": min_val,
            "peak_time": peak_time,
            "trend_direction": trend_direction
        }

    def _parse_time_range(self, time_range: str, now: int) -> int:
        """Parse time range string to Unix timestamp."""
        time_range = time_range.lower().strip()

        # Map time ranges
        multipliers = {
            "1h": 3600,
            "6h": 6 * 3600,
            "12h": 12 * 3600,
            "24h": 24 * 3600,
            "7d": 7 * 24 * 3600,
            "1d": 24 * 3600,
        }

        if time_range in multipliers:
            return now - multipliers[time_range]

        # Try to parse as hours
        if time_range.endswith("h"):
            try:
                hours = int(time_range[:-1])
                return now - hours * 3600
            except ValueError:
                pass

        # Default to 24 hours
        return now - 24 * 3600

    def format_duration(self, seconds: int) -> str:
        """Format duration in seconds to human readable string."""
        if seconds < 60:
            return f"{seconds}秒"
        elif seconds < 3600:
            return f"{seconds // 60}分钟"
        elif seconds < 86400:
            return f"{seconds // 3600}小时"
        else:
            return f"{seconds // 86400}天"
