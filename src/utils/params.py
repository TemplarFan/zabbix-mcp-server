"""参数解析工具"""
import re
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union


def parse_int_param(value: Any, default: Optional[int] = None) -> Optional[int]:
    """处理数值参数，兼容字符串形式的数字"""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def parse_time_param(value: Any, default: int) -> int:
    """
    将模型传来的值转换为Unix时间戳。
    支持：纯数字字符串、整数、以及相对时间描述（如 '1d', '24h', '1h'）
    """
    if value is None:
        return default

    # 如果是纯数字或数字字符串，直接转int
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        return int(value)

    # 处理语义化字符串 (例如: "24h", "1d", "7d")
    if isinstance(value, str):
        value = value.lower().strip()
        now = datetime.now()

        # 使用正则匹配：数字 + 单位
        match = re.match(r"(\d+)([hd])", value)
        if match:
            num = int(match.group(1))
            unit = match.group(2)
            if unit == 'h':
                return int((now - timedelta(hours=num)).timestamp())
            if unit == 'd':
                return int((now - timedelta(days=num)).timestamp())

        # 处理特定词汇
        if "yesterday" in value:
            return int((now - timedelta(days=1)).replace(hour=0, minute=0, second=0).timestamp())

    return default


def parse_list_param(value: Union[List[str], str, None]) -> Optional[List[str]]:
    """解析列表参数，支持多种输入格式"""
    if value is None:
        return None
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        try:
            # 尝试解析JSON数组
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
            return [str(parsed)]
        except json.JSONDecodeError:
            # 逗号分隔的字符串
            if ',' in value:
                return [v.strip() for v in value.split(',')]
            return [value]
    return None


def parse_dict_param(value: Union[Dict[str, Any], str, None]) -> Optional[Dict[str, Any]]:
    """解析字典参数，支持JSON字符串"""
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return None


def parse_list_of_dicts_param(value: Union[List[Dict[str, Any]], str, None]) -> Optional[List[Dict[str, Any]]]:
    """解析字典列表参数，支持JSON字符串"""
    if value is None:
        return None
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict):
                return [parsed]
            return None
        except json.JSONDecodeError:
            return None
    return None
