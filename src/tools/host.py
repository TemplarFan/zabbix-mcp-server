"""主机查询工具：host_get 精确/筛选查询与软件资产清单四级回退。"""
import logging
from typing import Annotated, Any, Dict, List, Optional, Union

from pydantic import Field

from client import get_zabbix_client
from utils.format import format_response
from utils.params import parse_dict_param, parse_int_param, parse_list_param


def _host_get_impl(client, hostids=None, name=None, groupids=None, templateids=None, output=None, search=None, filter=None, selectGroups=False, selectInventory=False, limit=10):
    """查询主机列表。支持ID精确查询或名称模糊匹配，已知IP时优先用get_host_by_ip"""

    # 1. 解析参数
    hostids = parse_list_param(hostids)
    groupids = parse_list_param(groupids)
    templateids = parse_list_param(templateids)
    search = parse_dict_param(search) or {}
    filter = parse_dict_param(filter)
    limit = parse_int_param(limit, 10)

    # 2. 核心逻辑：处理模糊匹配
    if name:
        search["name"] = f"*{name}*"

    # 3. 默认输出字段
    if output is None:
        output = ["hostid", "host", "name", "status", "available"]

    params = {
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
    if filter:
        params["filter"] = filter
    if selectGroups:
        params["selectGroups"] = ["groupid", "name"]
    if selectInventory:
        params["selectInventory"] = [
            "software", "software_full",
            "software_app_a", "software_app_b", "software_app_c",
            "software_app_d", "software_app_e"
        ]

    try:
        result = client.host.get(**params)

        if not result:
            search_info = name if name else (str(search) if search else '无')
            return f"未找到匹配项。搜索关键词: {search_info}"

        if len(result) >= limit:
            hint = f"\n(注意：仅显示前 {limit} 个匹配结果，请提供更精确的名称以缩小范围)"
            return format_response(result) + hint

        return format_response(result)
    except Exception as e:
        return f"查询过程中出现异常: {str(e)}"


def host_get(
    hostids: Annotated[Union[List[Any], str, int, None], Field(description="主机ID（单个或逗号分隔多个）")] = None,
    name: Annotated[Optional[str], Field(description="主机名关键词，模糊匹配")] = None,
    groupids: Annotated[Union[List[Any], str, int, None], Field(description="主机组ID筛选")] = None,
    templateids: Annotated[Union[List[Any], str, int, None], Field(description="模板ID筛选")] = None,
    output: Annotated[Union[str, List[str], None], Field(description="返回字段列表")] = None,
    search: Annotated[Union[Dict[str, str], str, None], Field(description="搜索条件字典")] = None,
    filter: Annotated[Union[Dict[str, Any], str, None], Field(description="精确过滤条件")] = None,
    selectGroups: Annotated[bool, Field(description="是否返回主机所属群组信息")] = False,
    selectInventory: Annotated[bool, Field(description="是否返回主机资产信息")] = False,
    limit: Annotated[Union[int, str, None], Field(description="返回数量（默认10）")] = 10
) -> str:
    """查询主机列表。支持ID精确查询或名称模糊匹配，已知IP时优先用get_host_by_ip"""
    return _host_get_impl(get_zabbix_client(), hostids, name, groupids, templateids, output, search, filter, selectGroups, selectInventory, limit)


def _host_software_inventory_get_impl(client, host_identifier):
    """查询单台主机的软件资产信息（software/software_full/software_app_a-e）"""

    # 软件相关字段
    software_fields = [
        "software",        # 软件
        "software_full",   # 软件详情
        "software_app_a",  # 软件应用A
        "software_app_b",  # 软件应用B
        "software_app_c",  # 软件应用C
        "software_app_d",  # 软件应用D
        "software_app_e"   # 软件应用E
    ]

    # 字段中文映射
    field_names = {
        "software": "软件",
        "software_full": "软件详情",
        "software_app_a": "软件应用A",
        "software_app_b": "软件应用B",
        "software_app_c": "软件应用C",
        "software_app_d": "软件应用D",
        "software_app_e": "软件应用E"
    }

    # 识别主机标识类型并查询
    host = None

    # 1. 尝试作为 hostid（纯数字）；失败仅记日志并继续后续回退
    # 终点语义：四路全空且无异常 → 未找到；曾有 API 异常 → 查询失败（不把失败伪装成未找到）
    query_errors = []
    if host_identifier.isdigit():
        try:
            result = client.host.get(
                hostids=[host_identifier],
                output=["hostid", "host", "name"],
                selectInventory=software_fields
            )
            if result:
                host = result[0]
        except Exception as exc:
            query_errors.append(f"按 hostid 查询: {exc}")
            logging.warning("host.get 按 hostid=%s 查询失败: %s", host_identifier, exc)

    # 2. 尝试作为 IP 地址查询
    if not host:
        try:
            interfaces = client.hostinterface.get(
                output=["hostid", "ip"],
                filter={"ip": host_identifier}
            )
            if interfaces:
                hostid = interfaces[0]["hostid"]
                result = client.host.get(
                    hostids=[hostid],
                    output=["hostid", "host", "name"],
                    selectInventory=software_fields
                )
                if result:
                    host = result[0]
        except Exception as exc:
            query_errors.append(f"按 IP 查询: {exc}")
            logging.warning("host.get 按 IP=%s 查询失败: %s", host_identifier, exc)

    # 3. 尝试作为主机名精确匹配
    if not host:
        try:
            result = client.host.get(
                output=["hostid", "host", "name"],
                selectInventory=software_fields,
                filter={"name": host_identifier}
            )
            if result:
                host = result[0]
        except Exception as exc:
            query_errors.append(f"按名称精确匹配: {exc}")
            logging.warning("host.get 按名称=%s 精确匹配失败: %s", host_identifier, exc)

    # 4. 尝试作为主机名模糊匹配
    if not host:
        try:
            result = client.host.get(
                output=["hostid", "host", "name"],
                selectInventory=software_fields,
                search={"name": f"*{host_identifier}*"},
                searchWildcardsEnabled=True,
                limit=1
            )
            if result:
                host = result[0]
        except Exception as exc:
            query_errors.append(f"按名称模糊匹配: {exc}")
            logging.warning("host.get 按名称=%s 模糊匹配失败: %s", host_identifier, exc)

    if not host:
        if query_errors:
            return (
                f"查询主机失败: {host_identifier}（解析路径存在 API 异常，首个: "
                f"{query_errors[0]}；不能确认为未找到）"
            )
        return f"未找到主机：{host_identifier}"

    # 提取信息
    hostid = host.get("hostid", "")
    host_name = host.get("name", "")
    host_ip = host.get("host", "")
    inventory = host.get("inventory", {})

    # 格式化输出
    lines = []
    lines.append(f"### 主机软件资产信息")
    lines.append(f"")
    lines.append(f"**主机ID**: {hostid}")
    lines.append(f"**主机名**: {host_name}")
    lines.append(f"**IP地址**: {host_ip}")
    lines.append(f"")

    # 检查是否有软件信息
    has_software = any(inventory.get(field) for field in software_fields)

    if not has_software:
        lines.append("该主机未填写软件资产信息")
        return "\n".join(lines)

    # 输出软件信息列表
    lines.append("| 字段 | 内容 |")
    lines.append("|------|------|")

    for field in software_fields:
        value = inventory.get(field, "")
        if value:
            lines.append(f"| {field_names[field]} | {value} |")

    return "\n".join(lines)


def host_software_inventory_get(
    host_identifier: Annotated[str, Field(description="主机标识（hostid/IP地址/主机名）")]
) -> str:
    """查询单台主机的软件资产信息（software/software_full/software_app_a-e）"""
    return _host_software_inventory_get_impl(get_zabbix_client(), host_identifier)
