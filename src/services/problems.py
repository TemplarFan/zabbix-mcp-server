"""Problem Service - Business logic for problem/alert operations."""
import logging
from typing import Any, Dict, List, Optional, Union
from zabbix_utils import ZabbixAPI

logger = logging.getLogger(__name__)


class ProblemService:
    """Service class for problem-related operations."""

    SEVERITY_MAP = {
        0: ("🔵 未分类", 0),
        1: ("🟢 信息", 0),
        2: ("🟡 警告", 0),
        3: ("🟠 一般", 0),
        4: ("🔴 严重", 0),
        5: ("🔴🔴 灾难", 0),
    }

    SEVERITY_LABELS = {
        5: "灾难",
        4: "严重",
        3: "一般",
        2: "警告",
        1: "信息",
        0: "未分类"
    }

    SEVERITY_EMOJI = {
        5: "🔴🔴",
        4: "🔴",
        3: "🟠",
        2: "🟡",
        1: "🟢",
        0: "⚪"
    }

    def __init__(self, client: ZabbixAPI):
        self.client = client

    def get_problems(
        self,
        hostids: Optional[List[str]] = None,
        time_from: Optional[int] = None,
        time_till: Optional[int] = None,
        severities: Optional[List[int]] = None,
        acknowledged: Optional[bool] = None,
        output: Optional[List[str]] = None,
        select_acknowledges: bool = False,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get problems with flexible filtering."""
        if output is None:
            output = ["eventid", "name", "severity", "clock", "objectid"]

        params: Dict[str, Any] = {
            "output": output,
            "limit": limit,
            "sortfield": "eventid",
            "sortorder": "DESC"
        }

        if hostids:
            params["hostids"] = hostids
        if time_from is not None:
            params["time_from"] = time_from
        if time_till is not None:
            params["time_till"] = time_till
        if severities:
            params["severities"] = severities
        if acknowledged is not None:
            params["acknowledged"] = acknowledged
        if select_acknowledges:
            params["selectAcknowledges"] = "extend"

        return self.client.problem.get(**params)

    def get_problems_with_hosts(
        self,
        hostids: Optional[List[str]] = None,
        time_from: Optional[int] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get problems with host information.

        Note: problem.get doesn't support selectHosts, so we need to
        query trigger.get separately to get host info.
        """
        # Get problems
        problems = self.get_problems(
            hostids=hostids,
            time_from=time_from,
            output=["eventid", "name", "severity", "clock", "objectid"],
            limit=limit
        )

        if not problems:
            return []

        # Get trigger IDs
        triggerids = [p.get("objectid") for p in problems if p.get("objectid")]

        if triggerids:
            # Get trigger info with hosts
            triggers = self.client.trigger.get(
                triggerids=triggerids,
                output=["triggerid"],
                selectHosts=["hostid", "name"]
            )

            # Create triggerid to hosts mapping
            trigger_host_map = {t["triggerid"]: t.get("hosts", []) for t in triggers}

            # Add host info to problems
            for problem in problems:
                triggerid = problem.get("objectid")
                if triggerid in trigger_host_map:
                    problem["hosts"] = trigger_host_map[triggerid]

        return problems

    def get_problem_summary(self, problems: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate summary statistics from problems list."""
        if not problems:
            return {"total": 0, "by_severity": {}, "top_problems": []}

        # Group by severity
        severity_counts = {sev: 0 for sev in self.SEVERITY_MAP.keys()}
        for p in problems:
            sev = p.get("severity", 0)
            if sev in severity_counts:
                severity_counts[sev] += 1

        # Sort by severity descending
        sorted_problems = sorted(problems, key=lambda x: x.get("severity", 0), reverse=True)
        top_problems = sorted_problems[:5]

        return {
            "total": len(problems),
            "by_severity": {sev: count for sev, count in severity_counts.items() if count > 0},
            "top_problems": top_problems
        }

    def format_problem_time(self, timestamp: Union[str, int, None]) -> str:
        """Format problem timestamp to readable string."""
        if not timestamp:
            return "-"

        from datetime import datetime
        try:
            dt = datetime.fromtimestamp(int(timestamp))
            return dt.strftime("%m-%d %H:%M")
        except (ValueError, TypeError):
            return str(timestamp)

    def get_host_problems(
        self,
        hostid: str,
        time_from: Optional[int] = None,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Get problems for a specific host."""
        return self.get_problems_with_hosts(
            hostids=[hostid],
            time_from=time_from,
            limit=limit
        )

    def count_problems_by_severity(
        self,
        hostids: Optional[List[str]] = None,
        time_from: Optional[int] = None
    ) -> Dict[int, int]:
        """Count problems grouped by severity."""
        problems = self.get_problems(
            hostids=hostids,
            time_from=time_from,
            output=["severity"],
            limit=1000  # Get all for counting
        )

        counts = {sev: 0 for sev in self.SEVERITY_MAP.keys()}
        for p in problems:
            sev = p.get("severity", 0)
            if sev in counts:
                counts[sev] += 1

        return counts
