"""Update Tools - MCP tools for host management operations."""

from typing import Annotated, List, Optional, Union

from pydantic import Field

from client import get_zabbix_client, validate_read_only
from utils.params import parse_list_param
from utils.format import format_response


def host_update(
    hostid: Annotated[Union[str, int], Field(description="主机ID")],
    new_name: Annotated[Optional[str], Field(description="新可见名称")] = None,
    add_groups: Annotated[Union[List, str, int, None], Field(description="要添加的群组ID（追加模式）")] = None,
    remove_groups: Annotated[Union[List, str, int, None], Field(description="要移除的群组ID")] = None
) -> str:
    """修改主机的可见名称和群组。群组参数为groupid（需先查询）"""
    validate_read_only()

    # 处理 hostid（可能是 int）
    hostid = str(hostid)

    add_groupids = parse_list_param(add_groups) or []
    remove_groupids = parse_list_param(remove_groups) or []

    client = get_zabbix_client()
    current = client.host.get(
        hostids=[hostid],
        output=["hostid", "name"],
        selectGroups=["groupid", "name"]
    )

    if not current:
        return f"错误：主机 {hostid} 不存在"

    old_name = current[0].get("name")
    current_groups = current[0].get("groups", [])
    current_groupids = [g["groupid"] for g in current_groups]
    current_group_names = [g["name"] for g in current_groups]

    final_groupids = current_groupids.copy()
    for g in add_groupids:
        if g not in final_groupids:
            final_groupids.append(g)
    final_groupids = [g for g in final_groupids if g not in remove_groupids]

    params = {"hostid": hostid}
    if new_name:
        params["name"] = new_name
    if add_groupids or remove_groupids:
        params["groups"] = [{"groupid": g} for g in final_groupids]

    result = client.host.update(**params)

    final_group_names = []
    if final_groupids:
        groups_info = client.hostgroup.get(
            groupids=final_groupids,
            output=["groupid", "name"]
        )
        final_group_names = [g["name"] for g in groups_info]

    return format_response({
        "hostid": hostid,
        "name": {"old": old_name, "new": new_name or old_name},
        "groups": {
            "old": current_group_names,
            "added": [g for g in final_group_names if g not in current_group_names],
            "removed": [g for g in current_group_names if g not in final_group_names],
            "final": final_group_names
        },
        "result": result
    })
