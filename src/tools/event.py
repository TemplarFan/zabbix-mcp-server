"""事件查询工具：eventid 游标分页、护栏预算预收缩与诚实翻页头。"""
import json
from typing import Annotated, Any, Dict, List, Optional, Union

from pydantic import Field

from client import get_zabbix_client
from .history import HISTORY_MAX_LIMIT
from services.event_paginator import iter_eventid_pages
from utils.format import (
    UNTRUSTED_PREAMBLE,
    format_response,
    get_max_response_chars,
    shrink_list_to_budget,
)
from utils.params import parse_int_param, parse_list_param, parse_time_param_strict

EVENT_QUERY_PAGE_SIZE = 1000


def _event_pagination_header(
    scanned: int,
    returned: int,
    has_more: bool,
    next_cursor: Optional[str],
) -> str:
    return "\n".join([
        "/* 翻页信息（不要展示给用户）：",
        f"- 候选扫描: {scanned}",
        f"- 实际返回: {returned}",
        f"- 是否还有更多: {'是' if has_more else '否'}",
        f"- 下一事件ID游标: {next_cursor or '无'}",
        (
            f"- 如需继续翻页: 使用 eventid_till={next_cursor}，原时间范围参数保持不变"
            if next_cursor
            else "- 已确认当前候选范围扫描完成"
        ),
        "*/",
        "",
    ])


def _event_get_impl(client, eventids=None, groupids=None, hostids=None, objectids=None, source=None, object_=None, value=None, severities=None, time_from=None, time_till=None, eventid_till=None, limit=10, output=None):
    """查询原始历史事件；业务状态解释使用问题事实明细工具。"""
    parsed_limit = parse_int_param(limit)
    if parsed_limit is None or parsed_limit <= 0:
        return "参数错误: limit 必须是正整数"
    if parsed_limit > HISTORY_MAX_LIMIT:
        return f"参数错误: limit 最大 {HISTORY_MAX_LIMIT}，请配合 eventid_till 翻页分批获取"

    value_filter = parse_int_param(value) if value is not None else None
    if value is not None and value_filter not in {0, 1}:
        return "参数错误: value 仅支持 0 或 1"

    cursor: Optional[str] = None
    if eventid_till is not None:
        cursor = str(eventid_till).strip()
        if not cursor.isdigit() or int(cursor) < 0:
            return "参数错误: eventid_till 必须是非负整数"

    try:
        parsed_time_from = parse_time_param_strict(time_from, "time_from")
        parsed_time_till = parse_time_param_strict(time_till, "time_till")
    except ValueError as exc:
        return f"参数错误: {exc}"
    if (
        parsed_time_from is not None
        and parsed_time_till is not None
        and parsed_time_from > parsed_time_till
    ):
        return "参数错误: time_from 不能晚于 time_till"

    parsed_source = parse_int_param(source) if source is not None else 0
    if source is not None and parsed_source is None:
        return "参数错误: source 必须是整数"
    parsed_object = parse_int_param(object_) if object_ is not None else None
    if object_ is not None and parsed_object is None:
        return "参数错误: object_ 必须是整数"

    try:
        parsed_severities: Optional[List[int]] = None
        if severities is not None:
            if isinstance(severities, list):
                parsed_severities = [int(item) for item in severities]
            elif isinstance(severities, str):
                try:
                    raw = json.loads(severities)
                except json.JSONDecodeError:
                    raw = [item.strip() for item in severities.split(",")]
                parsed_severities = [int(item) for item in (raw if isinstance(raw, list) else [raw])]
            else:
                parsed_severities = [int(severities)]
    except (TypeError, ValueError):
        return "参数错误: severities 必须是整数列表"

    parsed_eventids = parse_list_param(eventids)
    parsed_groupids = parse_list_param(groupids)
    parsed_hostids = parse_list_param(hostids)
    parsed_objectids = parse_list_param(objectids)

    if output is None:
        output = ["eventid", "name", "severity", "clock", "acknowledged", "objectid", "value", "r_eventid"]
    elif isinstance(output, str) and output != "extend":
        try:
            parsed_output = json.loads(output)
        except json.JSONDecodeError:
            parsed_output = [output]
        output = parsed_output if isinstance(parsed_output, list) else [str(parsed_output)]
    if isinstance(output, list):
        output = list(output)
        for required in ("eventid", "value"):
            if required not in output:
                output.append(required)

    base_params: Dict[str, Any] = {
        "output": output,
        "sortfield": "eventid",
        "sortorder": "DESC",
        "selectHosts": ["hostid", "name"],
    }
    for key, parsed in (
        ("eventids", parsed_eventids),
        ("groupids", parsed_groupids),
        ("hostids", parsed_hostids),
        ("objectids", parsed_objectids),
        ("severities", parsed_severities),
        ("source", parsed_source),
        ("object", parsed_object),
        ("time_from", parsed_time_from),
        ("time_till", parsed_time_till),
    ):
        if parsed is not None:
            base_params[key] = parsed

    returned_rows: List[Dict[str, Any]] = []
    scanned = 0
    has_more = False
    next_cursor: Optional[str] = None

    try:
        for paged in iter_eventid_pages(
            client.event, base_params, EVENT_QUERY_PAGE_SIZE, initial_eventid_till=cursor,
        ):
            scanned += 1
            if value_filter is None or parse_int_param(paged.row.get("value"), -1) == value_filter:
                returned_rows.append(paged.row)
            if len(returned_rows) >= parsed_limit:
                has_more = paged.has_more_after
                if has_more:
                    next_cursor = paged.next_cursor()
                break
    except Exception as exc:
        return f"查询失败: {exc}"

    # 翻页头与 JSON 体必须整体落在输出防护预算内：先按预算裁行，头部按实际给出的行数
    # 如实申报（否则防护层再截会使头部谎报行数，模型按游标续查会静默跳过被截行）。
    rows_before_guard = len(returned_rows)
    guard_budget = (
        get_max_response_chars()
        - len(UNTRUSTED_PREAMBLE) - 1
        - len(_event_pagination_header(scanned, 0, False, None)) - 2
        - 72  # 头部行数/游标数字从模板值增长的最坏余量
    )
    if rows_before_guard and guard_budget <= 0:
        return (
            "参数错误: 输出上限配置过小，单条事件也放不下；"
            "请调大 ZABBIX_MAX_RESPONSE_CHARS 或缩小 limit"
        )
    # 比例收缩与输出护栏共用 shrink_list_to_budget，防止两份算法漂移导致头部谎报行数
    returned_rows = returned_rows[:shrink_list_to_budget(returned_rows, lambda _k: guard_budget)]
    if rows_before_guard and not returned_rows:
        return (
            "参数错误: 单条事件序列化后即超过输出上限；请调大 "
            "ZABBIX_MAX_RESPONSE_CHARS 或缩小 limit 后重试"
        )

    if len(returned_rows) < rows_before_guard and returned_rows:
        # 防护确实裁掉了行：明确还有更多数据，游标指向最后给出的行
        has_more = True
        next_cursor = str(int(returned_rows[-1]["eventid"]) - 1)

    prefix = _event_pagination_header(
        scanned,
        len(returned_rows),
        has_more,
        next_cursor,
    )
    if scanned == 0:
        prefix += "查询结果为空：范围内没有候选事件。\n\n"
    elif not returned_rows:
        prefix += f"查询结果为空：候选事件中没有符合 value={value_filter} 的记录。\n\n"
    return prefix + format_response(returned_rows)


def event_get(
    eventids: Annotated[Union[List[Any], str, int, None], Field(description="事件ID")] = None,
    groupids: Annotated[Union[List[Any], str, int, None], Field(description="群组ID筛选")] = None,
    hostids: Annotated[Union[List[Any], str, int, None], Field(description="主机ID")] = None,
    objectids: Annotated[Union[List[Any], str, int, None], Field(description="触发器ID")] = None,
    source: Annotated[Union[int, str, None], Field(description="事件来源（默认0触发器事件）")] = None,
    object_: Annotated[Union[int, str, None], Field(description="事件对象类型")] = None,
    value: Annotated[Union[int, str, None], Field(description="本地筛选事件状态（1问题发生/0恢复）")] = None,
    severities: Annotated[Union[List[int], str, None], Field(description="严重级别列表")] = None,
    time_from: Annotated[Union[int, str, None], Field(description="起始时间（支持7d/24h或Unix时间戳）")] = None,
    time_till: Annotated[Union[int, str, None], Field(description="截止时间（支持相对时间或Unix时间戳）")] = None,
    eventid_till: Annotated[Union[int, str, None], Field(description="下一页事件ID游标；首次查询不传")] = None,
    limit: Annotated[Union[int, str, None], Field(description="最终返回数量（默认10，不是候选扫描上限）")] = 10,
    output: Annotated[Any, Field(description="返回字段列表")] = None,
) -> str:
    """查询原始历史事件；业务状态解释使用问题事实明细工具。"""
    return _event_get_impl(get_zabbix_client(), eventids, groupids, hostids, objectids, source, object_, value, severities, time_from, time_till, eventid_till, limit, output)
