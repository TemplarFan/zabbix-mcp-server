"""触发器与模板查询工具：阈值表达式展开与发现链。"""
import json
from typing import Annotated, Any, Dict, List, Union

from pydantic import Field

from client import get_zabbix_client
from utils.format import format_response
from utils.params import parse_dict_param, parse_int_param, parse_list_param


def _trigger_get_impl(client, triggerids=None, hostids=None, groupids=None, templateids=None, priority=None, output=None, search=None, filter=None, limit=20, include_expression=False, include_items=True):
    """查询触发器列表。priority=3,4,5只看严重以上级别"""

    # Parse parameters
    triggerids = parse_list_param(triggerids)
    hostids = parse_list_param(hostids)
    groupids = parse_list_param(groupids)
    templateids = parse_list_param(templateids)
    search = parse_dict_param(search)
    filter = parse_dict_param(filter)
    limit = parse_int_param(limit) or 20

    # Parse priority parameter
    if priority is not None:
        if isinstance(priority, str):
            try:
                parsed = json.loads(priority)
                if isinstance(parsed, list):
                    priority = [int(p) for p in parsed]
                else:
                    priority = int(parsed)
            except (json.JSONDecodeError, ValueError):
                if ',' in priority:
                    priority = [int(p.strip()) for p in priority.split(',')]
                else:
                    priority = int(priority)

    # Default to core fields for better performance, exclude expression to save tokens
    if output is None:
        output = ["triggerid", "description", "priority", "status", "state",
                  "value", "lastchange", "error"]
        if include_expression:
            output.extend(["expression", "recovery_expression"])

    params = {"output": output, "limit": limit}
    if include_expression or "expression" in output:
        # 展开表达式中的 functionid 和用户宏，否则返回 {id}>{$宏名} 形式读不出阈值
        params["expandExpression"] = True
    if include_items:
        params["selectItems"] = ["itemid", "name", "key_"]

    if triggerids:
        params["triggerids"] = triggerids
    if hostids:
        params["hostids"] = hostids
    if groupids:
        params["groupids"] = groupids
    if templateids:
        params["templateids"] = templateids
    if priority is not None:
        params["priority"] = priority
    if search:
        params["search"] = search
    if filter:
        params["filter"] = filter

    result = client.trigger.get(**params)
    return format_response(result)


def trigger_get(
    triggerids: Annotated[Union[List[Any], str, int, None], Field(description="触发器ID")] = None,
    hostids: Annotated[Union[List[Any], str, int, None], Field(description="主机ID筛选")] = None,
    groupids: Annotated[Union[List[Any], str, int, None], Field(description="群组ID筛选")] = None,
    templateids: Annotated[Union[List[Any], str, int, None], Field(description="模板ID筛选")] = None,
    priority: Annotated[Union[List[int], int, str, None], Field(description="严重级别（0未分类/1信息/2警告/3一般/4严重/5灾难）")] = None,
    output: Annotated[Union[str, List[str], None], Field(description="返回字段列表")] = None,
    search: Annotated[Union[Dict[str, str], str, None], Field(description="搜索条件")] = None,
    filter: Annotated[Union[Dict[str, Any], str, None], Field(description="精确过滤条件")] = None,
    limit: Annotated[Union[int, str, None], Field(description="返回数量（默认20）")] = 20,
    include_expression: Annotated[bool, Field(description="是否返回触发表达式（宏已展开，可直接读出阈值；默认False节省Token）")] = False,
    include_items: Annotated[bool, Field(description="是否带出触发器关联的监控项（itemid/name/key_，默认True）")] = True
) -> str:
    """查询触发器列表。priority=3,4,5只看严重以上级别；经触发器可精确定位其监控项"""
    return _trigger_get_impl(get_zabbix_client(), triggerids, hostids, groupids, templateids, priority, output, search, filter, limit, include_expression, include_items)


def _template_get_impl(client, templateids=None, search=None, limit=20, include_hosts=False):
    """查询模板。templateid 是 host_get templateids 筛选的唯一发现途径。"""
    templateids = parse_list_param(templateids)
    search = parse_dict_param(search)
    limit = parse_int_param(limit) or 20

    params = {"output": ["templateid", "name"], "limit": limit}
    if include_hosts:
        params["selectHosts"] = ["hostid", "name"]
    if templateids:
        params["templateids"] = templateids
    if search:
        params["search"] = search

    result = client.template.get(**params)
    return format_response(result)


def template_get(
    templateids: Annotated[Union[List[Any], str, int, None], Field(description="模板ID（精确查询）")] = None,
    search: Annotated[Union[Dict[str, str], str, None], Field(description="搜索条件（如按 name 模糊匹配）")] = None,
    limit: Annotated[Union[int, str, None], Field(description="返回数量（默认20）")] = 20,
    include_hosts: Annotated[bool, Field(description="是否带出应用该模板的主机（hostid/name，默认False）")] = False,
) -> str:
    """查询模板列表。拿到 templateid 后可用 host_get 的 templateids 参数筛选应用该模板的主机"""
    return _template_get_impl(get_zabbix_client(), templateids, search, limit, include_hosts)
