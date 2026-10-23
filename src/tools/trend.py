"""趋势分析工具：原始趋势查询与按样本数加权的趋势汇总。"""
import time
from datetime import datetime
from typing import Annotated, Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field

from client import get_zabbix_client
from utils.params import parse_int_param, parse_list_param
from utils.format import format_response
from ._analysis_common import BEIJING_TZ

# 入口护栏：单次返回条数与查询跨度上限（趋势为小时桶，31 天约 744 桶）
TREND_MAX_LIMIT = 500
TREND_MAX_SPAN_SECONDS = 31 * 86400


class TrendStats(BaseModel):
    """基础统计指标（基于每小时聚合数据）"""
    latest_avg: float = Field(description="最新聚合值（trend表最后一条avg，非实时值）")
    first_avg: float = Field(description="起始聚合值（trend表第一条avg）")
    avg_value: float = Field(description="平均值（所有avg记录的算术平均）")
    max_value: float = Field(description="峰值（所有max记录的最大值）")
    max_time: str = Field(description="峰值所在小时（整点时间，仅供参考）")
    min_value: float = Field(description="最小值（所有min记录的最小值）")
    min_time: str = Field(description="最小值所在小时（整点时间，仅供参考）")


class TrendChange(BaseModel):
    """变化趋势指标"""
    change_amount: float = Field(description="绝对变化量 = latest_avg - first_avg")
    change_rate: float = Field(description="相对变化率（%）= (change_amount / first_avg) × 100")


class TrendVolatility(BaseModel):
    """波动情况指标"""
    volatility: float = Field(description="波动幅度 = max - min")
    volatility_rate: float = Field(description="波动幅度占平均值比例（%）= (volatility / avg) × 100")


class TrendCoverage(BaseModel):
    """趋势时间桶与原始样本覆盖情况。"""
    requested_hours: int = Field(description="请求时间范围（小时）")
    time_from: int = Field(description="请求起始 Unix 时间戳")
    time_till: int = Field(description="请求截止 Unix 时间戳")
    valid_buckets: int = Field(description="样本数大于零的有效小时桶数量")
    total_samples: int = Field(description="有效小时桶的原始样本总数")
    bucket_coverage_percent: float = Field(description="有效小时桶占请求小时数的百分比")
    warning: Optional[str] = Field(default=None, description="缺桶或覆盖不足提示")


class TrendSummaryResult(BaseModel):
    """trend_summary 单个监控项返回结果"""
    itemid: str = Field(description="监控项ID")
    name: str = Field(description="监控项名称")
    units: str = Field(description="单位（如%、GB、Mbps）")
    stats: TrendStats = Field(description="基础统计指标")
    trend: TrendChange = Field(description="变化趋势指标")
    volatility: TrendVolatility = Field(description="波动情况指标")
    coverage: TrendCoverage = Field(description="趋势桶与样本覆盖情况")


class TrendSummaryErrorResponse(BaseModel):
    """trend_summary 错误响应"""
    error_type: str = Field(description="parameter_error/no_data/no_valid_samples/query_failed")
    error: str = Field(description="错误信息")
    itemids: List[str] = Field(description="请求的监控项ID列表")


def _trend_get_impl(client, itemids, time_from=None, time_till=None, limit=24):
    itemids = parse_list_param(itemids)
    limit = parse_int_param(limit, 24)
    time_from = parse_int_param(time_from)
    time_till = parse_int_param(time_till)

    # 入口护栏：条数与时间跨度上限，超过提示分段查询
    if limit and limit > TREND_MAX_LIMIT:
        return f"参数错误: limit 最大 {TREND_MAX_LIMIT}，请分批查询"
    span_reference = time_till if time_till else int(time.time())
    if time_from and span_reference - time_from > TREND_MAX_SPAN_SECONDS:
        return (
            f"参数错误: 查询跨度超过 31 天（上限 {TREND_MAX_SPAN_SECONDS // 86400} 天），"
            "请缩小 time_from/time_till 或分批查询"
        )

    params = {
        "itemids": itemids,
        "limit": limit
    }

    if time_from:
        params["time_from"] = time_from
    if time_till:
        params["time_till"] = time_till
    result = client.trend.get(**params)
    return format_response(result)


def trend_get(
    itemids: Annotated[Union[List[Any], str, int], Field(description="监控项ID（必填）")],
    time_from: Annotated[Union[int, str, None], Field(description="起始时间（支持相对时间如7d）")] = None,
    time_till: Annotated[Union[int, str, None], Field(description="截止时间")] = None,
    limit: Annotated[Union[int, str, None], Field(description="返回条数（默认24）")] = 24
) -> str:
    """获取监控项趋势数据（每小时聚合）。摘要用trend_summary"""
    return _trend_get_impl(get_zabbix_client(), itemids, time_from, time_till, limit)


def _trend_error(error_type: str, message: str, itemids: List[str]) -> TrendSummaryErrorResponse:
    return TrendSummaryErrorResponse(
        error_type=error_type,
        error=message,
        itemids=itemids,
    )


def _trend_summary_impl(client, itemids, hours):
    parsed_itemids = parse_list_param(itemids) or []
    normalized_itemids = [str(itemid).strip() for itemid in parsed_itemids if str(itemid).strip()]
    parsed_hours = parse_int_param(hours)
    if not normalized_itemids:
        return _trend_error("parameter_error", "itemids 不能为空", [])
    if len(normalized_itemids) > 3:
        return _trend_error("parameter_error", "itemids 最多3个", normalized_itemids)
    if parsed_hours is None or parsed_hours <= 0:
        return _trend_error("parameter_error", "hours 必须大于 0", normalized_itemids)

    time_till = int(time.time())
    time_from = time_till - parsed_hours * 3600
    try:
        items_info = client.item.get(
            itemids=normalized_itemids,
            output=["itemid", "name", "units"],
        )
    except Exception as exc:
        errors = [
            _trend_error("query_failed", f"item.get 失败: {exc}", [itemid])
            for itemid in normalized_itemids
        ]
        return errors[0] if len(errors) == 1 else errors

    item_info_map = {
        str(row.get("itemid")): {
            "name": str(row.get("name") or row.get("itemid")),
            "units": str(row.get("units", "")),
        }
        for row in items_info
        if row.get("itemid") is not None
    }
    results: List[Union[TrendSummaryResult, TrendSummaryErrorResponse]] = []
    for itemid in normalized_itemids:
        try:
            rows = client.trend.get(
                itemids=[itemid],
                time_from=time_from,
                time_till=time_till,
                output=["itemid", "value_avg", "value_max", "value_min", "clock", "num"],
                sortfield="clock",
                sortorder="ASC",
            )
        except Exception as exc:
            results.append(_trend_error("query_failed", str(exc), [itemid]))
            continue
        if not rows:
            results.append(_trend_error("no_data", "无趋势数据", [itemid]))
            continue

        valid_buckets: List[Dict[str, Any]] = []
        zero_sample_buckets = 0
        for row in rows:
            try:
                sample_count = int(row.get("num", 0))
                normalized = {
                    "clock": int(row["clock"]),
                    "value_avg": float(row["value_avg"]),
                    "value_max": float(row["value_max"]),
                    "value_min": float(row["value_min"]),
                    "num": sample_count,
                }
            except (KeyError, TypeError, ValueError):
                zero_sample_buckets += 1
                continue
            if sample_count <= 0:
                zero_sample_buckets += 1
                continue
            valid_buckets.append(normalized)

        if not valid_buckets:
            results.append(_trend_error(
                "no_valid_samples",
                "无有效样本：趋势桶样本数均为0或字段无效",
                [itemid],
            ))
            continue

        valid_buckets.sort(key=lambda row: row["clock"])
        total_samples = sum(row["num"] for row in valid_buckets)
        weighted_avg = sum(
            row["value_avg"] * row["num"] for row in valid_buckets
        ) / total_samples
        first_avg = valid_buckets[0]["value_avg"]
        latest_avg = valid_buckets[-1]["value_avg"]
        max_bucket = max(valid_buckets, key=lambda row: row["value_max"])
        min_bucket = min(valid_buckets, key=lambda row: row["value_min"])
        max_value = max_bucket["value_max"]
        min_value = min_bucket["value_min"]

        change_amount = latest_avg - first_avg
        rate_limit = 99999.9
        if abs(first_avg) < 0.0001:
            change_rate = 0.0 if abs(change_amount) < 0.0001 else rate_limit
        else:
            raw_change_rate = change_amount / abs(first_avg) * 100
            change_rate = max(-rate_limit, min(raw_change_rate, rate_limit))
        volatility = max_value - min_value
        if abs(weighted_avg) < 0.0001:
            volatility_rate = 0.0 if abs(volatility) < 0.0001 else rate_limit
        else:
            volatility_rate = min(volatility / abs(weighted_avg) * 100, rate_limit)

        valid_bucket_count = len(valid_buckets)
        coverage_percent = min(valid_bucket_count / parsed_hours * 100, 100.0)
        warning: Optional[str] = None
        if valid_bucket_count < parsed_hours or zero_sample_buckets:
            warning = (
                f"覆盖不足：请求 {parsed_hours} 小时，取得 {valid_bucket_count} 个有效小时桶，"
                f"忽略 {zero_sample_buckets} 个零样本或无效桶"
            )

        info = item_info_map.get(itemid, {"name": itemid, "units": ""})
        results.append(TrendSummaryResult(
            itemid=itemid,
            name=info["name"],
            units=info["units"],
            stats=TrendStats(
                latest_avg=round(latest_avg, 2),
                first_avg=round(first_avg, 2),
                avg_value=round(weighted_avg, 2),
                max_value=round(max_value, 2),
                max_time=datetime.fromtimestamp(max_bucket["clock"], tz=BEIJING_TZ).strftime("%Y-%m-%d %H:%M"),
                min_value=round(min_value, 2),
                min_time=datetime.fromtimestamp(min_bucket["clock"], tz=BEIJING_TZ).strftime("%Y-%m-%d %H:%M"),
            ),
            trend=TrendChange(
                change_amount=round(change_amount, 2),
                change_rate=round(change_rate, 1),
            ),
            volatility=TrendVolatility(
                volatility=round(volatility, 2),
                volatility_rate=round(volatility_rate, 1),
            ),
            coverage=TrendCoverage(
                requested_hours=parsed_hours,
                time_from=time_from,
                time_till=time_till,
                valid_buckets=valid_bucket_count,
                total_samples=total_samples,
                bucket_coverage_percent=round(coverage_percent, 1),
                warning=warning,
            ),
        ))

    return results[0] if len(results) == 1 else results


def trend_summary(
    itemids: Annotated[Union[List[Any], str, int], Field(description="监控项ID（最多3个）")],
    hours: Annotated[int, Field(description="查询时长。建议：磁盘168h、内存72h、CPU24h、网络48h")] = 24,
) -> Union[
    TrendSummaryResult,
    TrendSummaryErrorResponse,
    List[Union[TrendSummaryResult, TrendSummaryErrorResponse]],
]:
    """按趋势桶样本数加权汇总，并返回时间桶与样本覆盖情况。"""
    return _trend_summary_impl(get_zabbix_client(), itemids, hours)
