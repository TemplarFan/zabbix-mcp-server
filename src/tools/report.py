"""MCP 报表工具：查询 Zabbix 并返回日报、周报或月报 Markdown。"""

from typing import Annotated, Any

from pydantic import Field

from client import get_zabbix_client
from reporting.daily import generate_daily_report
from reporting.monthly import generate_monthly_report
from reporting.weekly import generate_weekly_report


class _ZabbixSdkCallAdapter:
    """把 zabbix_utils 客户端适配为 MCP 报表模块使用的调用接口。"""

    def __init__(self, client: Any) -> None:
        self._client = client

    def call(self, method: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        """调用指定的 Zabbix 只读方法。"""
        resource_name, operation_name = method.split(".", 1)
        resource = getattr(self._client, resource_name)
        operation = getattr(resource, operation_name)
        return operation(**params)


def event_daily_report(
    date: Annotated[
        str,
        Field(description="日报日期，支持 yesterday 或 YYYY-MM-DD，默认 yesterday"),
    ] = "yesterday",
    production_only: Annotated[
        bool,
        Field(description="是否仅统计生产口径，排除配置的测试网段（ZABBIX_TEST_NETWORKS）主机（默认False）"),
    ] = False,
    top_n_high_frequency: Annotated[
        int | None,
        Field(description="高频报警主机章节展示条数（>0前N条/0跳过章节/-1全部展示，默认20）"),
    ] = None,
    top_n_short_recovery: Annotated[
        int | None,
        Field(description="短时恢复型问题章节展示条数（>0前N条/0跳过章节/-1全部展示，默认-1）"),
    ] = None,
    top_n_chronic: Annotated[
        int | None,
        Field(description="持续型问题章节展示条数（>0前N条/0跳过章节/-1全部展示，默认-1）"),
    ] = None,
    top_n_disaster: Annotated[
        int | None,
        Field(description="严重事件中灾难子章节展示条数（>0前N条/0跳过章节/-1全部展示，默认-1）"),
    ] = None,
    top_n_severe: Annotated[
        int | None,
        Field(description="严重事件中严重子章节展示条数（>0前N条/0跳过章节/-1全部展示，默认-1）"),
    ] = None,
) -> str:
    """生成运维日报 Markdown，展示条数默认与定时推送日报一致，可按章节覆盖或仅统计生产口径。"""
    client = _ZabbixSdkCallAdapter(get_zabbix_client())
    top_limits = {
        "high_frequency": top_n_high_frequency,
        "short_recovery": top_n_short_recovery,
        "chronic": top_n_chronic,
        "disaster": top_n_disaster,
        "severe": top_n_severe,
    }
    return generate_daily_report(client, date, production_only=production_only, top_limits=top_limits)


def event_weekly_report(
    week: Annotated[
        str,
        Field(description="周内任意日期，支持 last_week 或 YYYY-MM-DD，默认 last_week"),
    ] = "last_week",
    production_only: Annotated[
        bool,
        Field(description="是否仅统计生产口径，排除配置的测试网段（ZABBIX_TEST_NETWORKS）主机（默认False）"),
    ] = False,
    top_n_high_frequency: Annotated[
        int | None,
        Field(description="高频报警主机章节展示条数（>0前N条/0跳过章节/-1全部展示，默认15）"),
    ] = None,
    top_n_regular: Annotated[
        int | None,
        Field(description="规律型问题章节展示条数（>0前N条/0跳过章节/-1全部展示，默认10）"),
    ] = None,
    top_n_short_recovery: Annotated[
        int | None,
        Field(description="短时恢复型问题章节展示条数（>0前N条/0跳过章节/-1全部展示，默认5）"),
    ] = None,
    top_n_chronic: Annotated[
        int | None,
        Field(description="持续型问题章节展示条数（>0前N条/0跳过章节/-1全部展示，默认10）"),
    ] = None,
    top_n_disaster: Annotated[
        int | None,
        Field(description="严重事件中灾难子章节展示条数（>0前N条/0跳过章节/-1全部展示，默认-1）"),
    ] = None,
    top_n_severe: Annotated[
        int | None,
        Field(description="严重事件中严重子章节展示条数（>0前N条/0跳过章节/-1全部展示，默认-1）"),
    ] = None,
) -> str:
    """生成周一至周日运维周报 Markdown，展示条数默认与定时推送周报一致，可按章节覆盖或仅统计生产口径。"""
    client = _ZabbixSdkCallAdapter(get_zabbix_client())
    top_limits = {
        "high_frequency": top_n_high_frequency,
        "regular": top_n_regular,
        "short_recovery": top_n_short_recovery,
        "chronic": top_n_chronic,
        "disaster": top_n_disaster,
        "severe": top_n_severe,
    }
    return generate_weekly_report(client, week, production_only=production_only, top_limits=top_limits)


def event_monthly_report(
    month: Annotated[
        str,
        Field(description="月报月份，支持 last_month 或 YYYY-MM，默认 last_month"),
    ] = "last_month",
    production_only: Annotated[
        bool,
        Field(description="是否仅统计生产口径，排除配置的测试网段（ZABBIX_TEST_NETWORKS）主机（默认False）"),
    ] = False,
    top_n_high_frequency: Annotated[
        int | None,
        Field(description="高频报警主机章节展示条数（>0前N条/0跳过章节/-1全部展示，默认10）"),
    ] = None,
    top_n_regular: Annotated[
        int | None,
        Field(description="规律型问题章节展示条数（>0前N条/0跳过章节/-1全部展示，默认5）"),
    ] = None,
    top_n_short_recovery: Annotated[
        int | None,
        Field(description="短时恢复型问题章节展示条数（>0前N条/0跳过章节/-1全部展示，默认5）"),
    ] = None,
    top_n_chronic: Annotated[
        int | None,
        Field(description="持续型问题章节展示条数（>0前N条/0跳过章节/-1全部展示，默认10）"),
    ] = None,
    top_n_disaster: Annotated[
        int | None,
        Field(description="严重事件中灾难子章节展示条数（>0前N条/0跳过章节/-1全部展示，默认5）"),
    ] = None,
    top_n_severe: Annotated[
        int | None,
        Field(description="严重事件中严重子章节展示条数（>0前N条/0跳过章节/-1全部展示，默认10）"),
    ] = None,
) -> str:
    """生成运维月报 Markdown，展示条数默认与定时推送月报一致，可按章节覆盖或仅统计生产口径。"""
    client = _ZabbixSdkCallAdapter(get_zabbix_client())
    top_limits = {
        "high_frequency": top_n_high_frequency,
        "regular": top_n_regular,
        "short_recovery": top_n_short_recovery,
        "chronic": top_n_chronic,
        "disaster": top_n_disaster,
        "severe": top_n_severe,
    }
    return generate_monthly_report(client, month, production_only=production_only, top_limits=top_limits)
