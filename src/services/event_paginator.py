"""共享的事件 ID 游标分页器。

problem.get / event.get 等按 eventid DESC + eventid_till 游标翻页的查询，
统一使用本模块，保证去重、终止条件、游标推进和防死循环校验只有一份实现。
"""

from __future__ import annotations

from typing import Any, Dict, Iterator, List, NamedTuple, Optional


class PagedRow(NamedTuple):
    """逐行模式的一行产出。

    eventid 是已校验的正整数；has_more_after 表示扫描批次在该行之后
    是否还有候选行（可能来自下一页）：页中恒为 True，短页最后一行为
    False——False 即整个候选范围确认扫描完成。续页游标用 next_cursor()。
    """

    row: Dict[str, Any]
    eventid: int
    has_more_after: bool

    def next_cursor(self) -> str:
        """以该行为界继续翻页时，应传给 eventid_till 的游标。"""
        return str(self.eventid - 1)


def _validated_eventid(row: Dict[str, Any], api_label: str) -> int:
    eventid = str(row.get("eventid", ""))
    if not eventid.isdigit() or int(eventid) <= 0:
        raise RuntimeError(f"{api_label} 返回了无效的 eventid")
    return int(eventid)


def iter_eventid_pages(
    endpoint: Any,
    base_params: Dict[str, Any],
    page_size: int,
    api_label: str = "event.get",
    initial_eventid_till: Optional[str] = None,
) -> Iterator[PagedRow]:
    """按 eventid DESC 游标逐页拉取，跨页去重后逐行产出 PagedRow。

    base_params 中的 sortfield/sortorder/limit 会被强制覆盖为
    eventid/DESC/page_size。initial_eventid_till 是调用方持有的续页
    游标，会注入首次请求并参与首页的游标前进校验。调用方提前停止即为
    合法用法，续页游标取最后产出行的 next_cursor()；生成器自然耗尽
    表示候选范围扫描完成。
    """
    if page_size <= 0:
        raise ValueError("page_size must be positive")
    return _iterate(endpoint, base_params, page_size, api_label, initial_eventid_till)


def _iterate(
    endpoint: Any,
    base_params: Dict[str, Any],
    page_size: int,
    api_label: str,
    initial_eventid_till: Optional[str],
) -> Iterator[PagedRow]:
    seen: set[str] = set()
    eventid_till = initial_eventid_till
    while True:
        params = {
            **base_params,
            "sortfield": "eventid",
            "sortorder": "DESC",
            "limit": page_size,
        }
        if eventid_till is not None:
            params["eventid_till"] = eventid_till

        page = endpoint.get(**params)
        if not page:
            return

        page_ids: List[int] = []
        for index, row in enumerate(page):
            numeric = _validated_eventid(row, api_label)
            page_ids.append(numeric)
            has_more_after = index < len(page) - 1 or len(page) >= page_size
            if str(numeric) in seen:
                continue
            seen.add(str(numeric))
            yield PagedRow(row, numeric, has_more_after)

        if len(page) < page_size:
            return

        next_cursor = min(page_ids) - 1
        if next_cursor < 0 or (eventid_till is not None and next_cursor >= int(eventid_till)):
            raise RuntimeError(f"{api_label} 分页游标未前进")
        eventid_till = str(next_cursor)


def fetch_all_eventid_pages(
    endpoint: Any,
    base_params: Dict[str, Any],
    page_size: int,
    api_label: str = "event.get",
    initial_eventid_till: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """翻页拉取全部结果（跨页去重），用于必须覆盖全量数据的统计。"""
    return [
        paged.row
        for paged in iter_eventid_pages(
            endpoint, base_params, page_size, api_label, initial_eventid_till,
        )
    ]
