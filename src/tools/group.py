"""主机组查询工具：组列表与组内主机。"""
from typing import Annotated, Any, List, Optional, Union

from pydantic import Field

from client import get_zabbix_client
from utils.format import format_response
from utils.params import parse_int_param, parse_list_param


def _hostgroup_get_impl(client, name=None, limit=50):
    """查询主机群组列表"""
    limit = parse_int_param(limit, 50)

    params = {
        "output": ["groupid", "name"],
        "limit": limit,
        "sortfield": "name",
        "sortorder": "ASC"
    }

    if name:
        params["search"] = {"name": f"*{name}*"}
        params["searchWildcardsEnabled"] = True

    result = client.hostgroup.get(**params)

    if not result:
        return f"未找到匹配的群组。搜索关键词: {name or '无'}"

    return format_response(result)


def hostgroup_get(
    name: Annotated[Optional[str], Field(description="群组名称关键词（模糊搜索）")] = None,
    limit: Annotated[Union[int, str, None], Field(description="返回数量（默认50）")] = 50
) -> str:
    """查询主机群组列表"""
    return _hostgroup_get_impl(get_zabbix_client(), name, limit)


def _hostgroup_get_hosts_impl(client, groupids, limit=50):
    """查询群组内的主机列表。需先通过hostgroup_get获取groupid"""
    groupids = parse_list_param(groupids)
    limit = parse_int_param(limit, 50)

    result = client.host.get(
        groupids=groupids,
        output=["hostid", "host", "name", "status"],
        limit=limit,
        sortfield="name",
        sortorder="ASC"
    )

    if not result:
        return f"群组 {groupids} 下无主机"

    # 统计信息
    total = len(result)
    enabled = sum(1 for h in result if h.get("status") == "0")
    disabled = total - enabled

    summary = f"群组 {groupids} 下共 {total} 台主机（启用: {enabled}, 禁用: {disabled})\n\n"
    return summary + format_response(result)


def hostgroup_get_hosts(
    groupids: Annotated[Union[List[Any], str, int], Field(description="群组ID（单个或逗号分隔多个）")],
    limit: Annotated[Union[int, str, None], Field(description="返回数量（默认50）")] = 50
) -> str:
    """查询群组内的主机列表。需先通过hostgroup_get获取groupid"""
    return _hostgroup_get_hosts_impl(get_zabbix_client(), groupids, limit)
