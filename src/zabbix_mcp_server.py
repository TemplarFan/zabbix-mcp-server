#!/usr/bin/env python3
"""
Zabbix MCP Server - Complete integration with Zabbix API using python-zabbix-utils

This server provides comprehensive access to Zabbix API functionality through
the Model Context Protocol (MCP), enabling AI assistants and other tools to
interact with Zabbix monitoring systems.

Author: Zabbix MCP Server Contributors
License: MIT
"""
import re
import time
from datetime import datetime, timedelta
import os
import json
import logging
from typing import Any, Dict, List, Optional, Union
from fastmcp import FastMCP
from zabbix_utils import ZabbixAPI
from dotenv import load_dotenv

# Import utility functions
from utils.params import (
    parse_int_param,
    parse_time_param,
    parse_list_param,
    parse_dict_param,
    parse_list_of_dicts_param
)
from utils.format import format_response, format_table

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO if os.getenv("DEBUG") else logging.WARNING,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Initialize FastMCP
mcp = FastMCP("Zabbix MCP Server")

# Global Zabbix API client
zabbix_api: Optional[ZabbixAPI] = None


def get_zabbix_client() -> ZabbixAPI:
    """Get or create Zabbix API client with proper authentication.
    
    Returns:
        ZabbixAPI: Authenticated Zabbix API client
        
    Raises:
        ValueError: If required environment variables are missing
        Exception: If authentication fails
    """
    global zabbix_api
    
    if zabbix_api is None:
        url = os.getenv("ZABBIX_URL")
        if not url:
            raise ValueError("ZABBIX_URL environment variable is required")
        
        logger.info(f"Initializing Zabbix API client for {url}")
        
        # Configure SSL verification
        verify_ssl = os.getenv("VERIFY_SSL", "true").lower() in ("true", "1", "yes")
        logger.info(f"SSL certificate verification: {'enabled' if verify_ssl else 'disabled'}")
        
        # Initialize client
        zabbix_api = ZabbixAPI(url=url, validate_certs=verify_ssl)

        # Authenticate using token or username/password
        token = os.getenv("ZABBIX_TOKEN")
        if token:
            logger.info("Authenticating with API token")
            zabbix_api.login(token=token)
        else:
            user = os.getenv("ZABBIX_USER")
            password = os.getenv("ZABBIX_PASSWORD")
            if not user or not password:
                raise ValueError("Either ZABBIX_TOKEN or ZABBIX_USER/ZABBIX_PASSWORD must be set")
            logger.info(f"Authenticating with username: {user}")
            zabbix_api.login(user=user, password=password)
        
        logger.info("Successfully authenticated with Zabbix API")
    
    return zabbix_api


def is_read_only() -> bool:
    """Check if server is in read-only mode.
    
    Returns:
        bool: True if read-only mode is enabled
    """
    return os.getenv("READ_ONLY", "true").lower() in ("true", "1", "yes")


def format_response(data: Any) -> str:
    """Format response data as JSON string.
    
    Args:
        data: Data to format
        
    Returns:
        str: JSON formatted string
    """
    return json.dumps(data, indent=2, default=str)


def validate_read_only() -> None:
    """Validate that write operations are allowed.

    Raises:
        ValueError: If server is in read-only mode
    """
    if is_read_only():
        raise ValueError("Server is in read-only mode - write operations are not allowed")


# # HOST MANAGEMENT
# @mcp.tool()
# def host_get(hostids: Union[List[str], str, None] = None,
#              groupids: Union[List[str], str, None] = None,
#              templateids: Union[List[str], str, None] = None,
#              output: Union[str, List[str], None] = None,
#              search: Union[Dict[str, str], str, None] = None,
#              filter: Union[Dict[str, Any], str, None] = None,
#              limit: Optional[int] = None) -> str:
#     """Get hosts from Zabbix with optional filtering.
#
#     Args:
#         hostids: List of host IDs to retrieve (or JSON string representation)
#         groupids: List of host group IDs to filter by (or JSON string representation)
#         templateids: List of template IDs to filter by (or JSON string representation)
#         output: Output format - defaults to core fields only for performance.
#                 Use "extend" for all fields, or specify list of fields needed.
#                 Default fields: hostid, host, name, status, available, error, maintenance_status
#         search: Search criteria (dict or JSON string)
#         filter: Filter criteria (dict or JSON string)
#         limit: Maximum number of results
#
#     Returns:
#         str: JSON formatted list of hosts
#     """
#     client = get_zabbix_client()
#
#     # Parse parameters
#     hostids = parse_list_param(hostids)
#     groupids = parse_list_param(groupids)
#     templateids = parse_list_param(templateids)
#     search = parse_dict_param(search)
#     filter = parse_dict_param(filter)
#     limit = parse_int_param(limit)
#
#     # Default to core fields for better performance
#     if output is None:
#         output = ["hostid", "host", "name", "status", "available", "error",
#                   "maintenance_status"]
#
#     params = {"output": output}
#
#     if hostids:
#         params["hostids"] = hostids
#     if groupids:
#         params["groupids"] = groupids
#     if templateids:
#         params["templateids"] = templateids
#     if search:
#         params["search"] = search
#     if filter:
#         params["filter"] = filter
#     if limit:
#         params["limit"] = limit
#
#     result = client.host.get(**params)
#     return format_response(result)
@mcp.tool()
def host_get(hostids: Union[List[str], str, None] = None,
             name: Optional[str] = None,  # 新增：显式支持名称模糊搜索
             groupids: Union[List[str], str, None] = None,
             templateids: Union[List[str], str, None] = None,
             output: Union[str, List[str], None] = None,
             search: Union[Dict[str, str], str, None] = None,
             filter: Union[Dict[str, Any], str, None] = None,
             limit: Union[int, str, None] = 10) -> str:  # 默认限制10条，保护Token
    """获取主机信息。支持通过ID精确查询或通过名称模糊查询。

    Args:
        hostids: 主机ID列表。
        name: 主机名关键词，支持模糊匹配（如输入“情报”可搜出“情报系统应用服务器”）。
        groupids: 主机组ID过滤。
        output: 返回字段，默认为核心字段。
        limit: 最大返回数量，默认10条，防止数据过载。
    """
    client = get_zabbix_client()

    # 1. 解析参数
    hostids = parse_list_param(hostids)
    groupids = parse_list_param(groupids)
    templateids = parse_list_param(templateids)
    search = parse_dict_param(search) or {}  # 初始化为字典
    filter = parse_dict_param(filter)
    limit = parse_int_param(limit, 10)

    # 2. 核心逻辑：处理模糊匹配
    if name:
        # 将 name 放入 search 参数中
        search["name"] = f"*{name}*"  # 自动补全通配符，让搜索更灵敏

    # 3. 默认输出字段
    if output is None:
        output = ["hostid", "host", "name", "status", "available"]

    params = {
        "output": output,
        "limit": limit,
        "searchWildcardsEnabled": True,  # 必须开启，否则通配符不生效
        "searchByAny": True  # 匹配任一条件即可
    }

    if hostids: params["hostids"] = hostids
    if groupids: params["groupids"] = groupids
    if templateids: params["templateids"] = templateids
    if search: params["search"] = search
    if filter: params["filter"] = filter

    try:
        result = client.host.get(**params)

        # 4. 结果反馈优化
        if not result:
            return f"未找到匹配项。搜索关键词: {name if name else '无'}"

        if len(result) >= limit:
            # 给出友好提示，告知可能还有更多
            hint = f"\n(注意：仅显示前 {limit} 个匹配结果，请提供更精确的名称以缩小范围)"
            return format_response(result) + hint

        return format_response(result)
    except Exception as e:
        return f"查询过程中出现异常: {str(e)}"

@mcp.tool()
def host_create(host: str, groups: Union[List[Dict[str, str]], str],
                interfaces: Union[List[Dict[str, Any]], str],
                templates: Union[List[Dict[str, str]], str, None] = None,
                inventory_mode: int = -1,
                status: int = 0) -> str:
    """Create a new host in Zabbix.

    Args:
        host: Host name
        groups: List of host groups (format: [{"groupid": "1"}] or JSON string)
        interfaces: List of host interfaces (or JSON string)
        templates: List of templates to link (format: [{"templateid": "1"}] or JSON string)
        inventory_mode: Inventory mode (-1=disabled, 0=manual, 1=automatic)
        status: Host status (0=enabled, 1=disabled)

    Returns:
        str: JSON formatted creation result
    """
    validate_read_only()

    # Parse parameters
    groups = parse_list_of_dicts_param(groups)
    interfaces = parse_list_of_dicts_param(interfaces)
    templates = parse_list_of_dicts_param(templates)

    client = get_zabbix_client()
    params = {
        "host": host,
        "groups": groups,
        "interfaces": interfaces,
        "inventory_mode": inventory_mode,
        "status": status
    }

    if templates:
        params["templates"] = templates

    result = client.host.create(**params)
    return format_response(result)


@mcp.tool()
def host_update(hostid: str, host: Optional[str] = None, 
                name: Optional[str] = None, status: Optional[int] = None) -> str:
    """Update an existing host in Zabbix.
    
    Args:
        hostid: Host ID to update
        host: New host name
        name: New visible name
        status: New status (0=enabled, 1=disabled)
        
    Returns:
        str: JSON formatted update result
    """
    validate_read_only()
    
    client = get_zabbix_client()
    params = {"hostid": hostid}
    
    if host:
        params["host"] = host
    if name:
        params["name"] = name
    if status is not None:
        params["status"] = status
    
    result = client.host.update(**params)
    return format_response(result)


@mcp.tool()
def host_delete(hostids: Union[List[str], str]) -> str:
    """Delete hosts from Zabbix.

    Args:
        hostids: List of host IDs to delete (or JSON string representation)

    Returns:
        str: JSON formatted deletion result
    """
    validate_read_only()

    # Parse parameters
    hostids = parse_list_param(hostids)

    client = get_zabbix_client()
    result = client.host.delete(*hostids)
    return format_response(result)


# HOST GROUP MANAGEMENT
@mcp.tool()
def hostgroup_get(groupids: Union[List[str], str, None] = None,
                  output: Union[str, List[str]] = "extend",
                  search: Union[Dict[str, str], str, None] = None,
                  filter: Union[Dict[str, Any], str, None] = None) -> str:
    """Get host groups from Zabbix.

    Args:
        groupids: List of group IDs to retrieve (or JSON string representation)
        output: Output format (extend or list of specific fields)
        search: Search criteria (dict or JSON string)
        filter: Filter criteria (dict or JSON string)

    Returns:
        str: JSON formatted list of host groups
    """
    client = get_zabbix_client()

    # Parse parameters
    groupids = parse_list_param(groupids)
    search = parse_dict_param(search)
    filter = parse_dict_param(filter)

    params = {"output": output}

    if groupids:
        params["groupids"] = groupids
    if search:
        params["search"] = search
    if filter:
        params["filter"] = filter

    result = client.hostgroup.get(**params)
    return format_response(result)


@mcp.tool()
def hostgroup_create(name: str) -> str:
    """Create a new host group in Zabbix.
    
    Args:
        name: Host group name
        
    Returns:
        str: JSON formatted creation result
    """
    validate_read_only()
    
    client = get_zabbix_client()
    result = client.hostgroup.create(name=name)
    return format_response(result)


@mcp.tool()
def hostgroup_update(groupid: str, name: str) -> str:
    """Update an existing host group in Zabbix.
    
    Args:
        groupid: Group ID to update
        name: New group name
        
    Returns:
        str: JSON formatted update result
    """
    validate_read_only()
    
    client = get_zabbix_client()
    result = client.hostgroup.update(groupid=groupid, name=name)
    return format_response(result)


@mcp.tool()
def hostgroup_delete(groupids: Union[List[str], str]) -> str:
    """Delete host groups from Zabbix.

    Args:
        groupids: List of group IDs to delete (or JSON string representation)

    Returns:
        str: JSON formatted deletion result
    """
    validate_read_only()

    # Parse parameters
    groupids = parse_list_param(groupids)

    client = get_zabbix_client()
    result = client.hostgroup.delete(*groupids)
    return format_response(result)


# ITEM MANAGEMENT
# @mcp.tool()
# def item_get(itemids: Union[List[str], str, None] = None,
#              hostids: Union[List[str], str, None] = None,
#              groupids: Union[List[str], str, None] = None,
#              templateids: Union[List[str], str, None] = None,
#              output: Union[str, List[str], None] = None,
#              search: Union[Dict[str, str], str, None] = None,
#              filter: Union[Dict[str, Any], str, None] = None,
#              limit: Union[int, str, None] = None) -> str:
#     """Get items from Zabbix with optional filtering.
#
#     Args:
#         itemids: List of item IDs to retrieve (or JSON string representation)
#         hostids: List of host IDs to filter by (or JSON string representation)
#         groupids: List of host group IDs to filter by (or JSON string representation)
#         templateids: List of template IDs to filter by (or JSON string representation)
#         output: Output format - defaults to core fields only for performance.
#                 Use "extend" for all fields, or specify list of fields needed.
#                 Default fields: itemid, name, key_, status, hostid, value_type, delay, type, units, lastvalue, error
#         search: Search criteria (dict or JSON string)
#         filter: Filter criteria (dict or JSON string)
#         limit: Maximum number of results
#
#     Returns:
#         str: JSON formatted list of items
#     """
#     client = get_zabbix_client()
#
#     # Parse parameters
#     itemids = parse_list_param(itemids)
#     hostids = parse_list_param(hostids)
#     groupids = parse_list_param(groupids)
#     templateids = parse_list_param(templateids)
#     search = parse_dict_param(search)
#     filter = parse_dict_param(filter)
#     limit = parse_int_param(limit)
#
#     # Default to core fields for better performance
#     if output is None:
#         output = ["itemid", "name", "key_", "status", "hostid", "value_type",
#                   "delay", "type", "units", "lastvalue", "error"]
#
#     params = {"output": output}
#
#     if itemids:
#         params["itemids"] = itemids
#     if hostids:
#         params["hostids"] = hostids
#     if groupids:
#         params["groupids"] = groupids
#     if templateids:
#         params["templateids"] = templateids
#     if search:
#         params["search"] = search
#     if filter:
#         params["filter"] = filter
#     if limit:
#         params["limit"] = limit
#
#     result = client.item.get(**params)
#     return format_response(result)


@mcp.tool()
def item_get(itemids: Union[List[str], str, None] = None,
             hostids: Union[List[str], str, None] = None,
             search: Union[Dict[str, str], str, None] = None,
             limit: Union[int, str, None] = None,
             output: Any = None) -> str:
    """获取监控项。支持 memory/cpu 等语义联想搜索，解决搜不到的问题。"""
    client = get_zabbix_client()

    # 1. 健壮性修复：强制将 search 解析为字典 (解决 'str' object has no attribute 'items')
    if isinstance(search, str):
        try:
            search = json.loads(search)
        except:
            # 如果不是 JSON 字符串，则构造标准字典
            search = {"name": search}

    # 2. 参数标准化
    hostids = parse_list_param(hostids)
    limit_val = parse_int_param(limit) or 20

    # 3. 语义增强 (应用 zabbixLLM 经验)
    # 当搜这些词时，自动扩展 Zabbix 常见的标准监控项关键字
    semantic_map = {
        "memory": ["memory", "utilization", "available", "used", "pused"],
        "cpu": ["cpu", "utilization", "load", "interrupt"],
        "disk": ["disk", "space", "util", "used", "free"],
        "filesystem": ["fs", "space", "util"]
    }

    params = {
        "output": ["itemid", "name", "key_", "units", "lastvalue"],
        "hostids": hostids,
        "limit": limit_val,
        "searchWildcardsEnabled": True,
        "searchByAny": True,
        "sortfield": "name"
    }

    if isinstance(search, dict):
        enhanced_search = {}
        for k, v in search.items():
            keyword = str(v).lower().strip("*")

            # 如果命中语义地图，将关键词组合成 Zabbix 支持的模式
            if keyword in semantic_map:
                # 组合关键词，如 "memory,utilization,available"
                # Zabbix search 不支持数组，我们选最核心的进行模糊匹配
                pattern = f"*{keyword}*"
            else:
                pattern = f"*{keyword}*"

            enhanced_search[k] = pattern
            # 模仿 zabbixLLM，强行同时搜索 key_
            if k == "name":
                enhanced_search["key_"] = pattern

        params["search"] = enhanced_search

    try:
        result = client.item.get(**params)

        # 4. Fallback 逻辑：如果还是搜不到，给出一个参考列表
        if not result and hostids:
            # 这是一个“安全探测”，列出该主机名字最像“核心指标”的 15 个项
            fallback = client.item.get(
                hostids=hostids,
                output=["name", "key_"],
                limit=15,
                search={"name": "*util*"},  # 优先找带 util 的
                searchByAny=True,
                searchWildcardsEnabled=True
            )
            if fallback:
                ref = "\n".join([f"- {i['name']} (Key: {i['key_']})" for i in fallback])
                return f"未找到精确匹配。根据您的需求，以下是该主机可能相关的监控项列表，请重新选择：\n{ref}"

        if not result:
            return "未找到匹配项，请尝试更简单的英文关键词。"

        return format_response(result)

    except Exception as e:
        return f"查询出错: {str(e)}"


@mcp.tool()
def item_create(name: str, key_: str, hostid: str, type: int,
                value_type: int, delay: str = "1m",
                units: Optional[str] = None,
                description: Optional[str] = None) -> str:
    """Create a new item in Zabbix.
    
    Args:
        name: Item name
        key_: Item key
        hostid: Host ID
        type: Item type (0=Zabbix agent, 2=Zabbix trapper, etc.)
        value_type: Value type (0=float, 1=character, 3=unsigned int, 4=text)
        delay: Update interval
        units: Value units
        description: Item description
        
    Returns:
        str: JSON formatted creation result
    """
    validate_read_only()
    
    client = get_zabbix_client()
    params = {
        "name": name,
        "key_": key_,
        "hostid": hostid,
        "type": type,
        "value_type": value_type,
        "delay": delay
    }
    
    if units:
        params["units"] = units
    if description:
        params["description"] = description
    
    result = client.item.create(**params)
    return format_response(result)


@mcp.tool()
def item_update(itemid: str, name: Optional[str] = None,
                key_: Optional[str] = None, delay: Optional[str] = None,
                status: Optional[int] = None) -> str:
    """Update an existing item in Zabbix.
    
    Args:
        itemid: Item ID to update
        name: New item name
        key_: New item key
        delay: New update interval
        status: New status (0=enabled, 1=disabled)
        
    Returns:
        str: JSON formatted update result
    """
    validate_read_only()
    
    client = get_zabbix_client()
    params = {"itemid": itemid}
    
    if name:
        params["name"] = name
    if key_:
        params["key_"] = key_
    if delay:
        params["delay"] = delay
    if status is not None:
        params["status"] = status
    
    result = client.item.update(**params)
    return format_response(result)


@mcp.tool()
def item_delete(itemids: Union[List[str], str]) -> str:
    """Delete items from Zabbix.

    Args:
        itemids: List of item IDs to delete (or JSON string representation)

    Returns:
        str: JSON formatted deletion result
    """
    validate_read_only()

    # Parse parameters
    itemids = parse_list_param(itemids)

    client = get_zabbix_client()
    result = client.item.delete(*itemids)
    return format_response(result)


# TRIGGER MANAGEMENT
@mcp.tool()
def trigger_get(triggerids: Union[List[str], str, None] = None,
                hostids: Union[List[str], str, None] = None,
                groupids: Union[List[str], str, None] = None,
                templateids: Union[List[str], str, None] = None,
                priority: Union[List[int], int, str, None] = None,
                output: Union[str, List[str], None] = None,
                search: Union[Dict[str, str], str, None] = None,
                filter: Union[Dict[str, Any], str, None] = None,
                limit: Union[int, str, None] = None) -> str:
    """Get triggers from Zabbix with optional filtering.

    Args:
        triggerids: List of trigger IDs to retrieve (or JSON string representation)
        hostids: List of host IDs to filter by (or JSON string representation)
        groupids: List of host group IDs to filter by (or JSON string representation)
        templateids: List of template IDs to filter by (or JSON string representation)
        priority: Priority/severity level(s) to filter by (0=Not classified, 1=Information,
                  2=Warning, 3=Average, 4=High, 5=Disaster). Can be int, list, or string like "4,5"
        output: Output format - defaults to core fields only for performance.
                Use "extend" for all fields, or specify list of fields needed.
                Default fields: triggerid, description, priority, status, state, value, lastchange, error, expression
        search: Search criteria (dict or JSON string)
        filter: Filter criteria (dict or JSON string)
        limit: Maximum number of results

    Returns:
        str: JSON formatted list of triggers
    """
    client = get_zabbix_client()

    # Parse parameters
    triggerids = parse_list_param(triggerids)
    hostids = parse_list_param(hostids)
    groupids = parse_list_param(groupids)
    templateids = parse_list_param(templateids)
    search = parse_dict_param(search)
    filter = parse_dict_param(filter)
    limit = parse_int_param(limit)

    # Parse priority parameter - can be int, list of ints, or comma-separated string
    if priority is not None:
        if isinstance(priority, str):
            # Try parsing as JSON array first
            try:
                parsed = json.loads(priority)
                if isinstance(parsed, list):
                    priority = [int(p) for p in parsed]
                else:
                    priority = int(parsed)
            except (json.JSONDecodeError, ValueError):
                # Try parsing as comma-separated values
                if ',' in priority:
                    priority = [int(p.strip()) for p in priority.split(',')]
                else:
                    priority = int(priority)

    # Default to core fields for better performance
    if output is None:
        output = ["triggerid", "description", "priority", "status", "state",
                  "value", "lastchange", "error", "expression"]

    params = {"output": output}

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
    if limit:
        params["limit"] = limit

    result = client.trigger.get(**params)
    return format_response(result)


@mcp.tool()
def trigger_create(description: str, expression: str,
                   priority: int = 0, status: int = 0,
                   comments: Optional[str] = None) -> str:
    """Create a new trigger in Zabbix.
    
    Args:
        description: Trigger description
        expression: Trigger expression
        priority: Severity (0=not classified, 1=info, 2=warning, 3=average, 4=high, 5=disaster)
        status: Status (0=enabled, 1=disabled)
        comments: Additional comments
        
    Returns:
        str: JSON formatted creation result
    """
    validate_read_only()
    
    client = get_zabbix_client()
    params = {
        "description": description,
        "expression": expression,
        "priority": priority,
        "status": status
    }
    
    if comments:
        params["comments"] = comments
    
    result = client.trigger.create(**params)
    return format_response(result)


@mcp.tool()
def trigger_update(triggerid: str, description: Optional[str] = None,
                   expression: Optional[str] = None, priority: Optional[int] = None,
                   status: Optional[int] = None) -> str:
    """Update an existing trigger in Zabbix.
    
    Args:
        triggerid: Trigger ID to update
        description: New trigger description
        expression: New trigger expression
        priority: New severity level
        status: New status (0=enabled, 1=disabled)
        
    Returns:
        str: JSON formatted update result
    """
    validate_read_only()
    
    client = get_zabbix_client()
    params = {"triggerid": triggerid}
    
    if description:
        params["description"] = description
    if expression:
        params["expression"] = expression
    if priority is not None:
        params["priority"] = priority
    if status is not None:
        params["status"] = status
    
    result = client.trigger.update(**params)
    return format_response(result)


@mcp.tool()
def trigger_delete(triggerids: Union[List[str], str]) -> str:
    """Delete triggers from Zabbix.

    Args:
        triggerids: List of trigger IDs to delete (or JSON string representation)

    Returns:
        str: JSON formatted deletion result
    """
    validate_read_only()

    # Parse parameters
    triggerids = parse_list_param(triggerids)

    client = get_zabbix_client()
    result = client.trigger.delete(*triggerids)
    return format_response(result)


# TEMPLATE MANAGEMENT
@mcp.tool()
def template_get(templateids: Union[List[str], str, None] = None,
                 groupids: Union[List[str], str, None] = None,
                 hostids: Union[List[str], str, None] = None,
                 output: Union[str, List[str]] = "extend",
                 search: Union[Dict[str, str], str, None] = None,
                 filter: Union[Dict[str, Any], str, None] = None) -> str:
    """Get templates from Zabbix with optional filtering.

    Args:
        templateids: List of template IDs to retrieve (or JSON string representation)
        groupids: List of host group IDs to filter by (or JSON string representation)
        hostids: List of host IDs to filter by (or JSON string representation)
        output: Output format (extend or list of specific fields)
        search: Search criteria (dict or JSON string)
        filter: Filter criteria (dict or JSON string)

    Returns:
        str: JSON formatted list of templates
    """
    client = get_zabbix_client()

    # Parse parameters
    templateids = parse_list_param(templateids)
    groupids = parse_list_param(groupids)
    hostids = parse_list_param(hostids)
    search = parse_dict_param(search)
    filter = parse_dict_param(filter)

    params = {"output": output}

    if templateids:
        params["templateids"] = templateids
    if groupids:
        params["groupids"] = groupids
    if hostids:
        params["hostids"] = hostids
    if search:
        params["search"] = search
    if filter:
        params["filter"] = filter

    result = client.template.get(**params)
    return format_response(result)


@mcp.tool()
def template_create(host: str, groups: Union[List[Dict[str, str]], str],
                    name: Optional[str] = None, description: Optional[str] = None) -> str:
    """Create a new template in Zabbix.

    Args:
        host: Template technical name
        groups: List of host groups (format: [{"groupid": "1"}] or JSON string)
        name: Template visible name
        description: Template description

    Returns:
        str: JSON formatted creation result
    """
    validate_read_only()

    # Parse parameters
    groups = parse_list_of_dicts_param(groups)

    client = get_zabbix_client()
    params = {
        "host": host,
        "groups": groups
    }

    if name:
        params["name"] = name
    if description:
        params["description"] = description

    result = client.template.create(**params)
    return format_response(result)


@mcp.tool()
def template_update(templateid: str, host: Optional[str] = None,
                    name: Optional[str] = None, description: Optional[str] = None) -> str:
    """Update an existing template in Zabbix.
    
    Args:
        templateid: Template ID to update
        host: New template technical name
        name: New template visible name
        description: New template description
        
    Returns:
        str: JSON formatted update result
    """
    validate_read_only()
    
    client = get_zabbix_client()
    params = {"templateid": templateid}
    
    if host:
        params["host"] = host
    if name:
        params["name"] = name
    if description:
        params["description"] = description
    
    result = client.template.update(**params)
    return format_response(result)


@mcp.tool()
def template_delete(templateids: Union[List[str], str]) -> str:
    """Delete templates from Zabbix.

    Args:
        templateids: List of template IDs to delete (or JSON string representation)

    Returns:
        str: JSON formatted deletion result
    """
    validate_read_only()

    # Parse parameters
    templateids = parse_list_param(templateids)

    client = get_zabbix_client()
    result = client.template.delete(*templateids)
    return format_response(result)


# PROBLEM MANAGEMENT
@mcp.tool()
def problem_get(eventids: Union[List[str], str, None] = None,
                groupids: Union[List[str], str, None] = None,
                hostids: Union[List[str], str, None] = None,
                objectids: Union[List[str], str, None] = None,
                output: Union[str, List[str], None] = None,
                time_from: Optional[int] = None,
                time_till: Optional[int] = None,
                recent: bool = False,
                severities: Union[List[int], str, None] = None,
                limit: Optional[int] = None) -> str:
    """Get problems from Zabbix with optional filtering.

    Args:
        eventids: List of event IDs to retrieve (or JSON string representation)
        groupids: List of host group IDs to filter by (or JSON string representation)
        hostids: List of host IDs to filter by (or JSON string representation)
        objectids: List of object IDs to filter by (or JSON string representation)
        output: Output format - defaults to core fields only for performance.
                Use "extend" for all fields, or specify list of fields needed.
                Default fields: eventid, objectid, name, severity, clock, acknowledged, r_eventid, suppressed
        time_from: Start time (Unix timestamp)
        time_till: End time (Unix timestamp)
        recent: Only recent problems
        severities: List of severity levels to filter by (or JSON string representation)
        limit: Maximum number of results

    Returns:
        str: JSON formatted list of problems
    """
    client = get_zabbix_client()

    # Parse parameters
    eventids = parse_list_param(eventids)
    groupids = parse_list_param(groupids)
    hostids = parse_list_param(hostids)
    objectids = parse_list_param(objectids)
    limit = parse_int_param(limit)
    time_from = parse_int_param(time_from)
    time_till = parse_int_param(time_till)

    if severities is not None and isinstance(severities, str):
        try:
            severities = json.loads(severities)
        except (json.JSONDecodeError, ValueError):
            severities = [int(severities)] if severities.isdigit() else None

    # Default to core fields for better performance
    if output is None:
        output = ["eventid", "objectid", "name", "severity", "clock",
                  "acknowledged", "r_eventid", "suppressed"]

    params = {"output": output}

    if eventids:
        params["eventids"] = eventids
    if groupids:
        params["groupids"] = groupids
    if hostids:
        params["hostids"] = hostids
    if objectids:
        params["objectids"] = objectids
    if time_from:
        params["time_from"] = time_from
    if time_till:
        params["time_till"] = time_till
    if recent:
        params["recent"] = recent
    if severities:
        params["severities"] = severities
    if limit:
        params["limit"] = limit

    result = client.problem.get(**params)
    return format_response(result)


# EVENT MANAGEMENT
@mcp.tool()
def event_get(eventids: Union[List[str], str, None] = None,
              groupids: Union[List[str], str, None] = None,
              hostids: Union[List[str], str, None] = None,
              objectids: Union[List[str], str, None] = None,
              output: Union[str, List[str]] = "extend",
              time_from: Optional[int] = None,
              time_till: Optional[int] = None,
              limit: Optional[int] = None) -> str:
    """Get events from Zabbix with optional filtering.

    Args:
        eventids: List of event IDs to retrieve (or JSON string representation)
        groupids: List of host group IDs to filter by (or JSON string representation)
        hostids: List of host IDs to filter by (or JSON string representation)
        objectids: List of object IDs to filter by (or JSON string representation)
        output: Output format (extend or list of specific fields)
        time_from: Start time (Unix timestamp)
        time_till: End time (Unix timestamp)
        limit: Maximum number of results

    Returns:
        str: JSON formatted list of events
    """
    client = get_zabbix_client()

    # Parse parameters
    eventids = parse_list_param(eventids)
    groupids = parse_list_param(groupids)
    hostids = parse_list_param(hostids)
    objectids = parse_list_param(objectids)
    limit = parse_int_param(limit)
    time_from = parse_int_param(time_from)
    time_till = parse_int_param(time_till)

    params = {"output": output}

    if eventids:
        params["eventids"] = eventids
    if groupids:
        params["groupids"] = groupids
    if hostids:
        params["hostids"] = hostids
    if objectids:
        params["objectids"] = objectids
    if time_from:
        params["time_from"] = time_from
    if time_till:
        params["time_till"] = time_till
    if limit:
        params["limit"] = limit

    result = client.event.get(**params)
    return format_response(result)


@mcp.tool()
def event_acknowledge(eventids: Union[List[str], str], action: int = 1,
                      message: Optional[str] = None) -> str:
    """Acknowledge events in Zabbix.

    Args:
        eventids: List of event IDs to acknowledge (or JSON string representation)
        action: Acknowledge action (1=acknowledge, 2=close, etc.)
        message: Acknowledge message

    Returns:
        str: JSON formatted acknowledgment result
    """
    validate_read_only()

    # Parse parameters
    eventids = parse_list_param(eventids)

    client = get_zabbix_client()
    params = {
        "eventids": eventids,
        "action": action
    }

    if message:
        params["message"] = message

    result = client.event.acknowledge(**params)
    return format_response(result)


# HISTORY MANAGEMENT
@mcp.tool()
def history_get(itemids: Union[List[str], str],
                history: Union[int, str] = 0,
                time_from: Union[int, str, None] = None,
                time_till: Union[int, str, None] = None,
                limit: Union[int, str, None] = None,
                sortfield: str = "clock",
                sortorder: str = "DESC") -> str:
    """Get history data from Zabbix.

    Args:
        itemids: List of item IDs to get history for (or JSON string representation)
        history: History type (0=float, 1=character, 2=log, 3=unsigned, 4=text)
        time_from: Start time (Unix timestamp)
        time_till: End time (Unix timestamp)
        limit: Maximum number of results
        sortfield: Field to sort by
        sortorder: Sort order (ASC or DESC)

    Returns:
        str: JSON formatted history data
    """
    # Parse parameters
    itemids = parse_list_param(itemids)
    history = parse_int_param(history)
    limit = parse_int_param(limit,10)
    time_from = parse_int_param(time_from)
    time_till = parse_int_param(time_till)

    client = get_zabbix_client()
    params = {
        "itemids": itemids,
        "history": history,
        "sortfield": sortfield,
        "sortorder": sortorder
    }



    if time_from:
        params["time_from"] = time_from
    if time_till:
        params["time_till"] = time_till
    if limit:
        params["limit"] = limit

    result = client.history.get(**params)
    return format_response(result)


# TREND MANAGEMENT
# @mcp.tool()
# def trend_get(itemids: Union[List[str], str],
#               time_from: Optional[int] = None,
#               time_till: Optional[int] = None,
#               limit: Optional[int] = None) -> str:
#     """Get trend data from Zabbix.
#
#     Args:
#         itemids: List of item IDs to get trends for (or JSON string representation)
#         time_from: Start time (Unix timestamp)
#         time_till: End time (Unix timestamp)
#         limit: Maximum number of results
#
#     Returns:
#         str: JSON formatted trend data
#     """
#     # Parse parameters
#     itemids = parse_list_param(itemids)
#     time_from = parse_int_param(time_from)
#     time_till = parse_int_param(time_till)
#     limit = parse_int_param(limit)
#
#     client = get_zabbix_client()
#     params = {"itemids": itemids}
#
#     if time_from:
#         params["time_from"] = time_from
#     if time_till:
#         params["time_till"] = time_till
#     if limit:
#         params["limit"] = limit
#
#     result = client.trend.get(**params)
#     return format_response(result)


def parse_semantic_time(time_val: Union[int, str, None], default_offset: int = 0) -> Optional[int]:
    """支持 Unix 时间戳或相对时间字符串 (如 '24h', '1d', '1h')"""
    if time_val is None:
        return None

    # 如果已经是数字或纯数字字符串
    if isinstance(time_val, int) or (isinstance(time_val, str) and time_val.isdigit()):
        return int(time_val)

    # 处理相对时间语义 (大模型最喜欢的模式)
    import time
    now = int(time.time())
    if isinstance(time_val, str):
        time_val = time_val.lower().strip()
        if time_val.endswith('h'):
            hours = int(time_val.replace('h', ''))
            return now - (hours * 3600)
        if time_val.endswith('d'):
            days = int(time_val.replace('d', ''))
            return now - (days * 86400)
        if time_val == 'now':
            return now

    return None


# 在 trend_get 中应用
@mcp.tool()
def trend_get(itemids: Union[List[str], str],
              time_from: Union[int, str, None] = None,
              time_till: Union[int, str, None] = None,
              limit: Union[int, str, None] = 24) -> str:
    """获取趋势。如果不传 time_from，默认获取最近 24 小时。"""

    # 1. 解析语义时间
    parsed_from = parse_semantic_time(time_from)
    parsed_till = parse_semantic_time(time_till)
    parsed_limit = parse_int_param(limit,24)

    # --- 核心优化：强制兜底时间窗口 ---
    if parsed_from is None:
        # 如果模型没传起始时间，强制设为 24 小时前
        import time
        parsed_from = int(time.time()) - (parsed_limit * 3600)
    # ------------------------------

    client = get_zabbix_client()
    params = {
        "itemids": parse_list_param(itemids),
        "output": ["itemid", "clock", "value_avg"],
        "limit": parsed_limit,
        "time_from": parsed_from,
        "sortfield": "clock",
        "sortorder": "DESC"  # 确保拿到的是最靠近现在的记录
    }

    if parsed_till:
        params["time_till"] = parsed_till

    try:
        result = client.trend.get(**params)

        # 按照时间正序排列（让 AI 看到的列表是从旧到新，符合逻辑趋势）
        result.reverse()

        from datetime import datetime
        for row in result:
            if "value_avg" in row:
                row["value_avg"] = round(float(row["value_avg"]), 2)
            if "clock" in row:
                dt = datetime.fromtimestamp(int(row["clock"]))
                # 增加年份，防止模型对“最新日期”产生怀疑
                row["time"] = dt.strftime('%Y-%m-%d %H:%M')

        import json
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return f"获取趋势失败: {str(e)}"


# USER MANAGEMENT
@mcp.tool()
def user_get(userids: Union[List[str], str, None] = None,
             output: Union[str, List[str]] = "extend",
             search: Union[Dict[str, str], str, None] = None,
             filter: Union[Dict[str, Any], str, None] = None) -> str:
    """Get users from Zabbix with optional filtering.

    Args:
        userids: List of user IDs to retrieve (or JSON string representation)
        output: Output format (extend or list of specific fields)
        search: Search criteria (dict or JSON string)
        filter: Filter criteria (dict or JSON string)

    Returns:
        str: JSON formatted list of users
    """
    client = get_zabbix_client()

    # Parse parameters
    userids = parse_list_param(userids)
    search = parse_dict_param(search)
    filter = parse_dict_param(filter)

    params = {"output": output}

    if userids:
        params["userids"] = userids
    if search:
        params["search"] = search
    if filter:
        params["filter"] = filter

    result = client.user.get(**params)
    return format_response(result)


@mcp.tool()
def user_create(username: str, passwd: str, usrgrps: Union[List[Dict[str, str]], str],
                name: Optional[str] = None, surname: Optional[str] = None,
                email: Optional[str] = None) -> str:
    """Create a new user in Zabbix.

    Args:
        username: Username
        passwd: Password
        usrgrps: List of user groups (format: [{"usrgrpid": "1"}] or JSON string)
        name: First name
        surname: Last name
        email: Email address

    Returns:
        str: JSON formatted creation result
    """
    validate_read_only()

    # Parse parameters
    usrgrps = parse_list_of_dicts_param(usrgrps)

    client = get_zabbix_client()
    params = {
        "username": username,
        "passwd": passwd,
        "usrgrps": usrgrps
    }

    if name:
        params["name"] = name
    if surname:
        params["surname"] = surname
    if email:
        params["email"] = email

    result = client.user.create(**params)
    return format_response(result)


@mcp.tool()
def user_update(userid: str, username: Optional[str] = None,
                name: Optional[str] = None, surname: Optional[str] = None,
                email: Optional[str] = None) -> str:
    """Update an existing user in Zabbix.
    
    Args:
        userid: User ID to update
        username: New username
        name: New first name
        surname: New last name
        email: New email address
        
    Returns:
        str: JSON formatted update result
    """
    validate_read_only()
    
    client = get_zabbix_client()
    params = {"userid": userid}
    
    if username:
        params["username"] = username
    if name:
        params["name"] = name
    if surname:
        params["surname"] = surname
    if email:
        params["email"] = email
    
    result = client.user.update(**params)
    return format_response(result)


@mcp.tool()
def user_delete(userids: Union[List[str], str]) -> str:
    """Delete users from Zabbix.

    Args:
        userids: List of user IDs to delete (or JSON string representation)

    Returns:
        str: JSON formatted deletion result
    """
    validate_read_only()

    # Parse parameters
    userids = parse_list_param(userids)

    client = get_zabbix_client()
    result = client.user.delete(*userids)
    return format_response(result)


# PROXY MANAGEMENT
@mcp.tool()
def proxy_get(proxyids: Union[List[str], str, None] = None,
              output: str = "extend",
              search: Union[Dict[str, str], str, None] = None,
              filter: Union[Dict[str, Any], str, None] = None,
              limit: Union[int, str, None] = None) -> str:
    """Get proxies from Zabbix with optional filtering.

    Args:
        proxyids: List of proxy IDs to retrieve (or JSON string representation)
        output: Output format (extend, shorten, or specific fields)
        search: Search criteria (dict or JSON string)
        filter: Filter criteria (dict or JSON string)
        limit: Maximum number of results

    Returns:
        str: JSON formatted list of proxies
    """
    client = get_zabbix_client()

    # Parse parameters
    proxyids = parse_list_param(proxyids)
    search = parse_dict_param(search)
    filter = parse_dict_param(filter)
    limit = parse_int_param(limit)

    params = {"output": output}

    if proxyids:
        params["proxyids"] = proxyids
    if search:
        params["search"] = search
    if filter:
        params["filter"] = filter
    if limit:
        params["limit"] = limit

    result = client.proxy.get(**params)
    return format_response(result)


@mcp.tool()
def proxy_create(host: str, status: int = 5,
                 description: Optional[str] = None,
                 tls_connect: int = 1,
                 tls_accept: int = 1) -> str:
    """Create a new proxy in Zabbix.
    
    Args:
        host: Proxy name
        status: Proxy status (5=active proxy, 6=passive proxy)
        description: Proxy description
        tls_connect: TLS connection settings (1=no encryption, 2=PSK, 4=certificate)
        tls_accept: TLS accept settings (1=no encryption, 2=PSK, 4=certificate)
        
    Returns:
        str: JSON formatted creation result
    """
    validate_read_only()
    
    client = get_zabbix_client()
    params = {
        "host": host,
        "status": status,
        "tls_connect": tls_connect,
        "tls_accept": tls_accept
    }
    
    if description:
        params["description"] = description
    
    result = client.proxy.create(**params)
    return format_response(result)


@mcp.tool()
def proxy_update(proxyid: str, host: Optional[str] = None,
                 status: Optional[int] = None,
                 description: Optional[str] = None,
                 tls_connect: Optional[int] = None,
                 tls_accept: Optional[int] = None) -> str:
    """Update an existing proxy in Zabbix.
    
    Args:
        proxyid: Proxy ID to update
        host: New proxy name
        status: New proxy status (5=active proxy, 6=passive proxy)
        description: New proxy description
        tls_connect: New TLS connection settings
        tls_accept: New TLS accept settings
        
    Returns:
        str: JSON formatted update result
    """
    validate_read_only()
    
    client = get_zabbix_client()
    params = {"proxyid": proxyid}
    
    if host:
        params["host"] = host
    if status is not None:
        params["status"] = status
    if description:
        params["description"] = description
    if tls_connect is not None:
        params["tls_connect"] = tls_connect
    if tls_accept is not None:
        params["tls_accept"] = tls_accept
    
    result = client.proxy.update(**params)
    return format_response(result)


@mcp.tool()
def proxy_delete(proxyids: Union[List[str], str]) -> str:
    """Delete proxies from Zabbix.

    Args:
        proxyids: List of proxy IDs to delete (or JSON string representation)

    Returns:
        str: JSON formatted deletion result
    """
    validate_read_only()

    # Parse parameters
    proxyids = parse_list_param(proxyids)

    client = get_zabbix_client()
    result = client.proxy.delete(*proxyids)
    return format_response(result)


# MAINTENANCE MANAGEMENT
@mcp.tool()
def maintenance_get(maintenanceids: Union[List[str], str, None] = None,
                    groupids: Union[List[str], str, None] = None,
                    hostids: Union[List[str], str, None] = None,
                    output: Union[str, List[str]] = "extend") -> str:
    """Get maintenance periods from Zabbix.

    Args:
        maintenanceids: List of maintenance IDs to retrieve (or JSON string representation)
        groupids: List of host group IDs to filter by (or JSON string representation)
        hostids: List of host IDs to filter by (or JSON string representation)
        output: Output format (extend or list of specific fields)

    Returns:
        str: JSON formatted list of maintenance periods
    """
    # Parse parameters
    maintenanceids = parse_list_param(maintenanceids)
    groupids = parse_list_param(groupids)
    hostids = parse_list_param(hostids)

    client = get_zabbix_client()
    params = {"output": output}
    
    if maintenanceids:
        params["maintenanceids"] = maintenanceids
    if groupids:
        params["groupids"] = groupids
    if hostids:
        params["hostids"] = hostids
    
    result = client.maintenance.get(**params)
    return format_response(result)


@mcp.tool()
def maintenance_create(name: str, active_since: int, active_till: int,
                       groupids: Union[List[str], str, None] = None,
                       hostids: Union[List[str], str, None] = None,
                       timeperiods: Union[List[Dict[str, Any]], str, None] = None,
                       description: Optional[str] = None) -> str:
    """Create a new maintenance period in Zabbix.

    Args:
        name: Maintenance name
        active_since: Start time (Unix timestamp)
        active_till: End time (Unix timestamp)
        groupids: List of host group IDs (or JSON string representation)
        hostids: List of host IDs (or JSON string representation)
        timeperiods: List of time periods (or JSON string representation)
                     Example: [{"timeperiod_type": 0, "start_date": 0, "period": 1800}]
        description: Maintenance description

    Returns:
        str: JSON formatted creation result
    """
    validate_read_only()

    # Parse parameters
    groupids = parse_list_param(groupids)
    hostids = parse_list_param(hostids)
    timeperiods = parse_list_of_dicts_param(timeperiods)

    client = get_zabbix_client()
    params = {
        "name": name,
        "active_since": active_since,
        "active_till": active_till
    }

    if groupids:
        params["groupids"] = groupids
    if hostids:
        params["hostids"] = hostids
    if timeperiods:
        params["timeperiods"] = timeperiods
    if description:
        params["description"] = description

    result = client.maintenance.create(**params)
    return format_response(result)


@mcp.tool()
def maintenance_update(maintenanceid: str, name: Optional[str] = None,
                       active_since: Optional[int] = None, active_till: Optional[int] = None,
                       description: Optional[str] = None) -> str:
    """Update an existing maintenance period in Zabbix.
    
    Args:
        maintenanceid: Maintenance ID to update
        name: New maintenance name
        active_since: New start time (Unix timestamp)
        active_till: New end time (Unix timestamp)
        description: New maintenance description
        
    Returns:
        str: JSON formatted update result
    """
    validate_read_only()
    
    client = get_zabbix_client()
    params = {"maintenanceid": maintenanceid}
    
    if name:
        params["name"] = name
    if active_since:
        params["active_since"] = active_since
    if active_till:
        params["active_till"] = active_till
    if description:
        params["description"] = description
    
    result = client.maintenance.update(**params)
    return format_response(result)


@mcp.tool()
def maintenance_delete(maintenanceids: Union[List[str], str]) -> str:
    """Delete maintenance periods from Zabbix.

    Args:
        maintenanceids: List of maintenance IDs to delete (or JSON string representation)

    Returns:
        str: JSON formatted deletion result
    """
    validate_read_only()

    # Parse parameters
    maintenanceids = parse_list_param(maintenanceids)

    client = get_zabbix_client()
    result = client.maintenance.delete(*maintenanceids)
    return format_response(result)


# GRAPH MANAGEMENT
@mcp.tool()
def graph_get(graphids: Union[List[str], str, None] = None,
              hostids: Union[List[str], str, None] = None,
              templateids: Union[List[str], str, None] = None,
              output: Union[str, List[str]] = "extend",
              search: Union[Dict[str, str], str, None] = None,
              filter: Union[Dict[str, Any], str, None] = None) -> str:
    """Get graphs from Zabbix with optional filtering.

    Args:
        graphids: List of graph IDs to retrieve (or JSON string representation)
        hostids: List of host IDs to filter by (or JSON string representation)
        templateids: List of template IDs to filter by (or JSON string representation)
        output: Output format (extend or list of specific fields)
        search: Search criteria (dict or JSON string)
        filter: Filter criteria (dict or JSON string)

    Returns:
        str: JSON formatted list of graphs
    """
    # Parse parameters
    graphids = parse_list_param(graphids)
    hostids = parse_list_param(hostids)
    templateids = parse_list_param(templateids)
    search = parse_dict_param(search)
    filter = parse_dict_param(filter)

    client = get_zabbix_client()
    params = {"output": output}

    if graphids:
        params["graphids"] = graphids
    if hostids:
        params["hostids"] = hostids
    if templateids:
        params["templateids"] = templateids
    if search:
        params["search"] = search
    if filter:
        params["filter"] = filter

    result = client.graph.get(**params)
    return format_response(result)


# DISCOVERY RULE MANAGEMENT
@mcp.tool()
def discoveryrule_get(itemids: Union[List[str], str, None] = None,
                      hostids: Union[List[str], str, None] = None,
                      templateids: Union[List[str], str, None] = None,
                      output: Union[str, List[str]] = "extend",
                      search: Union[Dict[str, str], str, None] = None,
                      filter: Union[Dict[str, Any], str, None] = None) -> str:
    """Get discovery rules from Zabbix with optional filtering.

    Args:
        itemids: List of discovery rule IDs to retrieve (or JSON string representation)
        hostids: List of host IDs to filter by (or JSON string representation)
        templateids: List of template IDs to filter by (or JSON string representation)
        output: Output format (extend or list of specific fields)
        search: Search criteria (dict or JSON string)
        filter: Filter criteria (dict or JSON string)

    Returns:
        str: JSON formatted list of discovery rules
    """
    # Parse parameters
    itemids = parse_list_param(itemids)
    hostids = parse_list_param(hostids)
    templateids = parse_list_param(templateids)
    search = parse_dict_param(search)
    filter = parse_dict_param(filter)

    client = get_zabbix_client()
    params = {"output": output}

    if itemids:
        params["itemids"] = itemids
    if hostids:
        params["hostids"] = hostids
    if templateids:
        params["templateids"] = templateids
    if search:
        params["search"] = search
    if filter:
        params["filter"] = filter
    
    result = client.discoveryrule.get(**params)
    return format_response(result)


# ITEM PROTOTYPE MANAGEMENT
@mcp.tool()
def itemprototype_get(itemids: Union[List[str], str, None] = None,
                      discoveryids: Union[List[str], str, None] = None,
                      hostids: Union[List[str], str, None] = None,
                      output: Union[str, List[str]] = "extend",
                      search: Union[Dict[str, str], str, None] = None,
                      filter: Union[Dict[str, Any], str, None] = None) -> str:
    """Get item prototypes from Zabbix with optional filtering.

    Args:
        itemids: List of item prototype IDs to retrieve (or JSON string representation)
        discoveryids: List of discovery rule IDs to filter by (or JSON string representation)
        hostids: List of host IDs to filter by (or JSON string representation)
        output: Output format (extend or list of specific fields)
        search: Search criteria (dict or JSON string)
        filter: Filter criteria (dict or JSON string)

    Returns:
        str: JSON formatted list of item prototypes
    """
    # Parse parameters
    itemids = parse_list_param(itemids)
    discoveryids = parse_list_param(discoveryids)
    hostids = parse_list_param(hostids)
    search = parse_dict_param(search)
    filter = parse_dict_param(filter)

    client = get_zabbix_client()
    params = {"output": output}

    if itemids:
        params["itemids"] = itemids
    if discoveryids:
        params["discoveryids"] = discoveryids
    if hostids:
        params["hostids"] = hostids
    if search:
        params["search"] = search
    if filter:
        params["filter"] = filter

    result = client.itemprototype.get(**params)
    return format_response(result)


# CONFIGURATION EXPORT/IMPORT
@mcp.tool()
def configuration_export(format: str = "json",
                         options: Union[Dict[str, Any], str, None] = None) -> str:
    """Export configuration from Zabbix.

    Args:
        format: Export format (json, xml)
        options: Export options (dict or JSON string)

    Returns:
        str: JSON formatted export result
    """
    # Parse parameters
    options = parse_dict_param(options)

    client = get_zabbix_client()
    params = {"format": format}

    if options:
        params["options"] = options

    result = client.configuration.export(**params)
    return format_response(result)


@mcp.tool()
def configuration_import(format: str, source: str,
                         rules: Union[Dict[str, Any], str]) -> str:
    """Import configuration to Zabbix.

    Args:
        format: Import format (json, xml)
        source: Configuration data to import
        rules: Import rules (dict or JSON string)

    Returns:
        str: JSON formatted import result
    """
    validate_read_only()

    # Parse parameters
    rules = parse_dict_param(rules)

    client = get_zabbix_client()
    params = {
        "format": format,
        "source": source,
        "rules": rules
    }

    result = client.configuration.import_(**params)
    return format_response(result)


# MACRO MANAGEMENT
@mcp.tool()
def usermacro_get(globalmacroids: Union[List[str], str, None] = None,
                  hostids: Union[List[str], str, None] = None,
                  output: Union[str, List[str]] = "extend",
                  search: Union[Dict[str, str], str, None] = None,
                  filter: Union[Dict[str, Any], str, None] = None) -> str:
    """Get global macros from Zabbix with optional filtering.

    Args:
        globalmacroids: List of global macro IDs to retrieve (or JSON string representation)
        hostids: List of host IDs to filter by (for host macros) (or JSON string representation)
        output: Output format (extend or list of specific fields)
        search: Search criteria (dict or JSON string)
        filter: Filter criteria (dict or JSON string)

    Returns:
        str: JSON formatted list of global macros
    """
    # Parse parameters
    globalmacroids = parse_list_param(globalmacroids)
    hostids = parse_list_param(hostids)
    search = parse_dict_param(search)
    filter = parse_dict_param(filter)

    client = get_zabbix_client()
    params = {"output": output}

    if globalmacroids:
        params["globalmacroids"] = globalmacroids
    if hostids:
        params["hostids"] = hostids
    if search:
        params["search"] = search
    if filter:
        params["filter"] = filter

    result = client.usermacro.get(**params)
    return format_response(result)


# SYSTEM INFO
@mcp.tool()
def apiinfo_version() -> str:
    """Get Zabbix API version information.
    
    Returns:
        str: JSON formatted API version info
    """
    client = get_zabbix_client()
    result = client.apiinfo.version()
    return format_response(result)


def get_transport_config() -> Dict[str, Any]:
    """Get transport configuration from environment variables.
    
    Returns:
        Dict[str, Any]: Transport configuration
        
    Raises:
        ValueError: If invalid transport configuration
    """
    transport = os.getenv("ZABBIX_MCP_TRANSPORT", "stdio").lower()
    
    if transport not in ["stdio", "streamable-http"]:
        raise ValueError(f"Invalid ZABBIX_MCP_TRANSPORT: {transport}. Must be 'stdio' or 'streamable-http'")
    
    config = {"transport": transport}
    
    if transport == "streamable-http":
        # Check AUTH_TYPE requirement
        auth_type = os.getenv("AUTH_TYPE", "").lower()
        if auth_type != "no-auth":
            raise ValueError("AUTH_TYPE must be set to 'no-auth' when using streamable-http transport")
        
        # Get HTTP configuration with defaults
        config.update({
            "host": os.getenv("ZABBIX_MCP_HOST", "127.0.0.1"),
            "port": int(os.getenv("ZABBIX_MCP_PORT", "8000")),
            "stateless_http": os.getenv("ZABBIX_MCP_STATELESS_HTTP", "false").lower() in ("true", "1", "yes")
        })
        
        logger.info(f"HTTP transport configured: {config['host']}:{config['port']}, stateless_http={config['stateless_http']}")
    
    return config


# ==================== Summary Tools for Dify/LLM ====================

@mcp.tool()
def get_problem_summary(
    hostids: Optional[str] = None,
    time_range: str = "24h",
    group_by: str = "severity"
) -> str:
    """
    获取告警摘要（已聚合），适合对话场景直接展示

    比 problem_get 更适合LLM展示，返回Markdown格式，无需二次处理

    Args:
        hostids: 主机ID列表（逗号分隔或JSON数组），不传则查询全部
        time_range: 时间范围，支持 "1h", "24h", "7d", "yesterday"
        group_by: 分组方式，默认按严重程度

    Returns:
        Markdown格式的告警摘要，包含统计和详情

    Example:
        get_problem_summary(time_range="24h")
        get_problem_summary(hostids="10084,10085", time_range="1h")
    """
    client = get_zabbix_client()

    # 解析参数
    hostid_list = parse_list_param(hostids)

    # 计算时间
    now = int(time.time())
    time_from = parse_time_param(time_range, now - 86400)  # 默认24小时

    # 构建查询参数
    params = {
        "output": ["eventid", "name", "severity", "clock", "objectid"],
    }

    if hostid_list:
        params["hostids"] = hostid_list

    if time_from:
        params["time_from"] = time_from

    # 查询
    problems = client.problem.get(**params)

    # 按严重程度排序（API不支持，在本地排序）
    problems = sorted(problems, key=lambda x: x.get("severity", 0), reverse=True)

    if not problems:
        return "✅ 当前没有告警"

    # 按严重程度分组统计
    severity_map = {
        0: ("🔵 未分类", 0),
        1: ("🟢 信息", 0),
        2: ("🟡 警告", 0),
        3: ("🟠 一般", 0),
        4: ("🔴 严重", 0),
        5: ("🔴🔴 灾难", 0),
    }

    for p in problems:
        sev = p.get("severity", 0)
        if sev in severity_map:
            label, count = severity_map[sev]
            severity_map[sev] = (label, count + 1)

    lines = ["## 告警概览\n"]

    # 统计摘要
    total = len(problems)
    lines.append(f"**总计: {total} 个告警**\n")

    for sev in sorted(severity_map.keys(), reverse=True):
        label, count = severity_map[sev]
        if count > 0:
            lines.append(f"{label}: {count}个")

    lines.append("")

    # 详细列表（只展示最严重的5个）
    if problems:
        lines.append("### 最严重的5个告警\n")

        headers = ["时间", "主机", "问题", "级别"]
        rows = []

        # 批量获取主机信息：收集所有触发器ID，一次性查询
        triggerids = [p.get("objectid", "") for p in problems[:5] if p.get("objectid")]
        host_map = {}  # triggerid -> hostname
        if triggerids:
            try:
                triggers = client.trigger.get(
                    triggerids=triggerids,
                    output=["triggerid"],
                    selectHosts=["name"]
                )
                for t in triggers:
                    if t.get("hosts"):
                        host_map[t["triggerid"]] = t["hosts"][0].get("name", "未知")
            except:
                pass

        for p in problems[:5]:
            # 格式化时间
            ts = p.get("clock", "")
            if ts:
                try:
                    dt = datetime.fromtimestamp(int(ts))
                    time_str = dt.strftime("%m-%d %H:%M")
                except:
                    time_str = str(ts)
            else:
                time_str = "-"

            # 从缓存中获取主机名
            triggerid = p.get("objectid", "")
            host = host_map.get(triggerid, "未知")
            desc = p.get("name", "无描述")[:30]  # 截断

            sev = p.get("severity", 0)
            sev_label = {5: "灾难", 4: "严重", 3: "一般", 2: "警告", 1: "信息"}.get(sev, "未分类")

            rows.append([time_str, host, desc, sev_label])

        lines.append(format_table(headers, rows))

    return "\n".join(lines)


@mcp.tool()
def check_host_health(host_identifier: str, time_range: str = "1h") -> str:
    """
    一站式检查主机健康状况 - 适合"帮我看看XX服务器怎么样"这种场景

    自动识别 host_identifier 类型（IP/主机名/hostid），返回完整的健康报告

    Args:
        host_identifier: 主机标识（IP地址、主机名或hostid）
        time_range: 查询时间范围，默认1小时

    Returns:
        Markdown格式的健康报告，包含：
        - 主机基本信息
        - 当前告警
        - 关键指标（CPU/内存/磁盘）
        - 健康建议

    Example:
        check_host_health("172.18.6.220")
        check_host_health("情报系统应用服务器")
    """
    client = get_zabbix_client()

    # 1. 识别并查找hostid
    hostid = _resolve_host_identifier(client, host_identifier)
    if not hostid:
        return f"❌ 未找到主机: {host_identifier}，请检查主机名或IP是否正确"

    # 2. 获取主机信息
    hosts = client.host.get(
        hostids=[hostid],
        output=["hostid", "name", "available", "error", "status"],
        selectInterfaces=["ip", "dns"]
    )
    if not hosts:
        return f"❌ 无法获取主机信息: {host_identifier}"

    host = hosts[0]

    # 3. 获取告警
    problems = client.problem.get(
        hostids=[hostid],
        output=["eventid", "name", "severity", "clock"]
    )

    # 4. 获取关键监控项
    items = client.item.get(
        hostids=[hostid],
        search={"key_": ["system.cpu.util", "vm.memory.util", "vfs.fs.size"]},
        output=["itemid", "name", "key_", "lastvalue", "units"]
    )

    return _format_host_overview(host, problems, items)


@mcp.tool()
def quick_status() -> str:
    """
    快速查看Zabbix整体状态 - 适合每日巡检

    Returns:
        整体状态摘要，包含：
        - 主机总数和状态统计
        - 告警统计
        - 其他关键指标
    """
    client = get_zabbix_client()

    lines = ["# 📊 Zabbix 整体状态\n"]

    # 1. 主机统计 - 获取所有主机
    hosts = client.host.get(
        output=["hostid", "available", "status"],
        selectInterfaces=["type"]
    )
    total = len(hosts)
    enabled = sum(1 for h in hosts if h.get("status") == "0")
    disabled = sum(1 for h in hosts if h.get("status") == "1")

    # 按监控状态分类
    available_count = sum(1 for h in hosts if h.get("available") == "1")
    unavailable_count = sum(1 for h in hosts if h.get("available") == "2")
    unknown_count = sum(1 for h in hosts if h.get("available") == "0")

    lines.append(f"## 🖥️ 主机统计")
    lines.append(f"- 主机总数: {total}")
    lines.append(f"- 🟢 已启用: {enabled}")
    lines.append(f"- ➖ 已禁用: {disabled}")
    lines.append(f"")
    lines.append(f"### 监控状态（基于 Zabbix Agent）")
    lines.append(f"- 🟢 可用: {available_count}")
    lines.append(f"- 🔴 不可用: {unavailable_count}")
    lines.append(f"- ⚪ 未知（无 Agent）: {unknown_count}")
    lines.append("")

    # 2. 告警统计
    problems = client.problem.get(
        output=["severity"]
    )

    lines.append(f"## ⚠️ 当前告警")
    if problems:
        severity_count = {}
        for p in problems:
            sev = int(p.get("severity", 0))
            severity_count[sev] = severity_count.get(sev, 0) + 1

        total_problems = len(problems)
        lines.append(f"**总计: {total_problems} 个问题**\n")

        for sev in sorted(severity_count.keys(), reverse=True):
            emoji = {5: "🔴🔴", 4: "🔴", 3: "🟠", 2: "🟡", 1: "🔵", 0: "⚪"}.get(sev, "⚪")
            name = {5: "灾难", 4: "严重", 3: "一般", 2: "警告", 1: "信息", 0: "未分类"}.get(sev, "其他")
            lines.append(f"{emoji} {name}: {severity_count[sev]}个")
    else:
        lines.append("✅ 当前无告警")

    lines.append("")

    # 3. 触发器统计
    triggers = client.trigger.get(
        output=["triggerid", "status", "state", "value"],
        filter={"status": "0"}  # 只统计启用状态的触发器
    )
    if triggers:
        total_trig = len(triggers)
        problem_trig = sum(1 for t in triggers if t.get("value") == "1")
        ok_trig = sum(1 for t in triggers if t.get("value") == "0")

        lines.append(f"## 🔔 触发器状态")
        lines.append(f"- 启用中: {total_trig}")
        lines.append(f"- 🔴 有问题: {problem_trig}")
        lines.append(f"- 🟢 正常: {ok_trig}")

    return "\n".join(lines)


def _resolve_host_identifier(client, identifier: str) -> Optional[str]:
    """
    解析主机标识符，返回hostid

    支持：
    1. 纯数字（认为是hostid）
    2. IP地址格式（搜索interfaces）
    3. 主机名（模糊搜索）
    """
    # 1. 检查是否是纯数字（hostid）
    if identifier.isdigit():
        return identifier

    # 2. 检查是否是IP地址
    ip_pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
    if re.match(ip_pattern, identifier):
        interfaces = client.hostinterface.get(
            output=["hostid"],
            filter={"ip": identifier}
        )
        if interfaces:
            return interfaces[0]["hostid"]
        return None

    # 3. 按主机名搜索（模糊匹配）
    hosts = client.host.get(
        output=["hostid", "name"],
        search={"name": identifier},
        searchWildcardsEnabled=True,
        limit=5
    )

    if len(hosts) == 1:
        return hosts[0]["hostid"]
    elif len(hosts) > 1:
        # 如果有多个匹配，返回第一个
        return hosts[0]["hostid"]

    return None


def _format_host_overview(host: Dict, problems: List[Dict], items: List[Dict]) -> str:
    """格式化主机概览"""
    lines = []

    # 主机基本信息
    host_name = host.get("name", "未知")
    host_ip = host.get("interfaces", [{}])[0].get("ip", "N/A") if host.get("interfaces") else "N/A"
    status = "🟢 正常" if host.get("available") == "1" else "🔴 不可用"

    lines.append(f"## 🖥️ {host_name}")
    lines.append(f"- IP: {host_ip}")
    lines.append(f"- 状态: {status}")
    lines.append("")

    # 告警摘要
    if problems:
        lines.append(f"### ⚠️ 告警 ({len(problems)}个)")
        for p in problems[:3]:  # 只展示前3个
            desc = p.get("name", "无描述")
            sev = p.get("severity", 0)
            sev_emoji = {5: "🔴🔴", 4: "🔴", 3: "🟠", 2: "🟡", 1: "🟢"}.get(sev, "⚪")
            lines.append(f"{sev_emoji} {desc}")
        lines.append("")
    else:
        lines.append("✅ 无告警\n")

    # 关键指标
    key_metrics = {}
    for item in items:
        key = item.get("key_", "")
        if "cpu.util" in key:
            key_metrics["CPU"] = item.get("lastvalue", "N/A")
        elif "memory.util" in key or "vm.memory.util" in key:
            key_metrics["内存"] = item.get("lastvalue", "N/A")
        elif "vfs.fs.size" in key and "pused" in key:
            key_metrics["磁盘"] = item.get("lastvalue", "N/A")

    if key_metrics:
        lines.append("### 📊 关键指标")
        for name, value in key_metrics.items():
            lines.append(f"- {name}: {value}%")

    return "\n".join(lines)


def main():
    """Main entry point for uv execution."""
    logger.info("Starting Zabbix MCP Server")
    
    # Get transport configuration
    try:
        transport_config = get_transport_config()
        logger.info(f"Transport: {transport_config['transport']}")
    except ValueError as e:
        logger.error(f"Transport configuration error: {e}")
        return 1
    
    # Log configuration
    logger.info(f"Read-only mode: {is_read_only()}")
    logger.info(f"Zabbix URL: {os.getenv('ZABBIX_URL', 'Not configured')}")
    
    try:
        if transport_config["transport"] == "stdio":
            mcp.run()
        else:  # streamable-http
            mcp.run(
                transport="streamable-http",
                host=transport_config["host"],
                port=transport_config["port"],
                stateless_http=transport_config["stateless_http"]
            )
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {e}")
        raise


@mcp.tool()
def get_host_by_ip(ip: str) -> str:
    """
    通过IP地址精确获取主机的hostid和名称。
    这是最节省Token的定位方式，建议在已知IP时优先使用。

    Args:
        ip: 主机的IP地址 (例如 "192.168.1.1")
    """
    client = get_zabbix_client()

    # 仿照你的 zabbix_llm_workflow.py 逻辑
    params = {
        "output": ["hostid"],
        "selectHosts": ["hostid", "name", "status"],
        "filter": {
            "ip": ip
        }
    }

    # 调用 hostinterface.get
    result = client.hostinterface.get(**params)

    if not result:
        return f"未找到 IP 为 {ip} 的主机接口配置。"

    # 提取主机信息
    hosts = result[0].get("hosts", [])
    if not hosts:
        return f"找到接口但未关联主机，IP: {ip}"

    # 只返回最核心的信息，极度节省Token
    return format_response(hosts)


@mcp.tool()
def inspect_host_performance(
        hostid: Union[str, int, List[str]],
        range_hours: Union[int, str] = 24
) -> str:
    """
    一键获取主机整体的核心巡检数据。
    """
    client = get_zabbix_client()
    hostids = parse_list_param(hostid)
    hours = parse_int_param(range_hours, 24)

    if not hostids: return "未提供有效的 hostid"
    target_id = hostids[0]

    # 定义取值配置 (逻辑参考 zabbixLLM)
    configs = [
        {"key": "cpu", "t_name": "component", "t_val": "cpu", "trend": True},
        {"key": "memory", "t_name": "component", "t_val": "memory", "trend": True},
        {"key": "disk", "t_name": "disk", "t_val": "", "trend": False},
        {"key": "filesystem", "t_name": "filesystem", "t_val": "", "trend": False},
        {"key": "oracle", "t_name": "Application", "t_val": "Oracle", "trend": False}
    ]

    report = {}
    now = int(time.time())
    start_time = now - (hours * 3600)

    for cfg in configs:
        # 1. 获取实时数据 (模仿 fetch_result)
        tag_filter = {"tag": cfg["t_name"], "operator": 0}
        if cfg["t_val"]: tag_filter["value"] = cfg["t_val"]

        items = client.item.get(
            hostids=target_id,
            tags=[tag_filter],
            output=["itemid", "name", "lastvalue", "units", "value_type"],
            filter={"status": 0}
        )

        report[cfg["key"]] = {"current": items, "trends": []}

        # 2. 获取趋势数据 (模仿 fetch_resource_trend)
        if cfg["trend"] and items:
            # 仅对该分类下的第一个监控项取趋势，防止数据爆炸
            primary_item = items[0]["itemid"]
            trends = client.trend.get(
                itemids=primary_item,
                time_from=start_time,
                time_till=now,
                output=["clock", "value_avg", "value_max"]
            )
            report[cfg["key"]]["trends"] = trends

    return format_response(report)

if __name__ == "__main__":
    main()
