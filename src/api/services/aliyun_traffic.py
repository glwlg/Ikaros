from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo


CDT_MONTHLY_FREE_QUOTA_GB = Decimal("20")
ALIYUN_CLI_TIMEOUT_SECONDS = 20
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
_BYTES_PER_GB = Decimal(1024) ** 3
_UNIT_BYTES = {
    "b": Decimal(1),
    "byte": Decimal(1),
    "bytes": Decimal(1),
    "kb": Decimal(1024),
    "kib": Decimal(1024),
    "mb": Decimal(1024) ** 2,
    "mib": Decimal(1024) ** 2,
    "gb": _BYTES_PER_GB,
    "gib": _BYTES_PER_GB,
    "tb": Decimal(1024) ** 4,
    "tib": Decimal(1024) ** 4,
}


class AliyunTrafficError(RuntimeError):
    pass


class AliyunCliUnavailable(AliyunTrafficError):
    pass


class AliyunCliTimeout(AliyunTrafficError):
    pass


class AliyunCliCommandError(AliyunTrafficError):
    pass


class AliyunApiError(AliyunTrafficError):
    pass


class AliyunTrafficDataError(AliyunTrafficError):
    pass


def _decimal_value(value: Any, *, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise AliyunTrafficDataError(f"阿里云账单的 {field} 无法解析: {value}") from exc
    if not parsed.is_finite():
        raise AliyunTrafficDataError(f"阿里云账单的 {field} 不是有限数值")
    return parsed


def _usage_to_gb(value: Any, unit: Any) -> Decimal:
    usage = _decimal_value(value, field="Usage")
    if usage < 0:
        raise AliyunTrafficDataError("阿里云账单的 Usage 不能为负数")
    normalized_unit = str(unit or "").strip().lower()
    unit_bytes = _UNIT_BYTES.get(normalized_unit)
    if unit_bytes is None:
        raise AliyunTrafficDataError(f"不支持的阿里云流量单位: {unit or '空值'}")
    return usage * unit_bytes / _BYTES_PER_GB


def _rounded_float(value: Decimal, places: str = "0.000001") -> float:
    return float(value.quantize(Decimal(places)))


def build_cdt_traffic_summary(
    items: Iterable[dict[str, Any]],
    *,
    billing_cycle: str,
    queried_at: str | None = None,
) -> dict[str, Any]:
    grouped: dict[tuple[str, str, str], Decimal] = {}

    for item in items:
        if not isinstance(item, dict):
            raise AliyunTrafficDataError("阿里云账单明细格式错误")
        raw_usage = item.get("Usage")
        if raw_usage is None or str(raw_usage).strip() == "":
            continue
        usage_gb = _usage_to_gb(raw_usage, item.get("UsageUnit"))
        key = (
            str(item.get("BillingItem") or item.get("ProductDetail") or "CDT 流量").strip(),
            str(item.get("BillingItemCode") or "").strip(),
            str(item.get("Region") or "global").strip(),
        )
        grouped[key] = grouped.get(key, Decimal(0)) + usage_gb

    used_gb = sum(grouped.values(), Decimal(0))
    remaining_gb = max(Decimal(0), CDT_MONTHLY_FREE_QUOTA_GB - used_gb)
    overage_gb = max(Decimal(0), used_gb - CDT_MONTHLY_FREE_QUOTA_GB)
    usage_percent = used_gb / CDT_MONTHLY_FREE_QUOTA_GB * Decimal(100)
    detail_items = [
        {
            "billing_item": billing_item,
            "billing_item_code": billing_item_code,
            "region": region,
            "usage_gb": _rounded_float(usage_gb),
        }
        for (billing_item, billing_item_code, region), usage_gb in grouped.items()
    ]
    detail_items.sort(
        key=lambda item: (
            -float(item["usage_gb"]),
            str(item["billing_item"]),
            str(item["region"]),
        )
    )

    timestamp = queried_at or datetime.now(_SHANGHAI_TZ).isoformat(timespec="seconds")
    return {
        "billing_cycle": billing_cycle,
        "quota_gb": _rounded_float(CDT_MONTHLY_FREE_QUOTA_GB),
        "used_gb": _rounded_float(used_gb),
        "remaining_gb": _rounded_float(remaining_gb),
        "overage_gb": _rounded_float(overage_gb),
        "usage_percent": _rounded_float(usage_percent, "0.01"),
        "queried_at": timestamp,
        "items": detail_items,
    }


def _command_error_detail(stdout: str, stderr: str) -> str:
    for candidate in (stdout, stderr):
        payload_text = candidate.strip()
        if not payload_text:
            continue
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError:
            first_line = payload_text.splitlines()[0].strip()
            return first_line[:400]
        if isinstance(payload, dict):
            code = str(payload.get("Code") or "").strip()
            message = str(payload.get("Message") or "").strip()
            detail = ": ".join(part for part in (code, message) if part)
            if detail:
                return detail[:400]
    return "阿里云 CLI 调用失败"


async def _run_aliyun_cli(arguments: list[str]) -> dict[str, Any]:
    try:
        process = await asyncio.create_subprocess_exec(
            "aliyun",
            *arguments,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise AliyunCliUnavailable("服务器未安装阿里云 CLI") from exc

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(),
            timeout=ALIYUN_CLI_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as exc:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        with contextlib.suppress(Exception):
            await process.communicate()
        raise AliyunCliTimeout(
            f"阿里云流量查询超过 {ALIYUN_CLI_TIMEOUT_SECONDS} 秒"
        ) from exc

    stdout = (stdout_bytes or b"").decode("utf-8", errors="replace")
    stderr = (stderr_bytes or b"").decode("utf-8", errors="replace")
    if process.returncode != 0:
        raise AliyunCliCommandError(_command_error_detail(stdout, stderr))

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise AliyunCliCommandError("阿里云 CLI 未返回 JSON 数据") from exc
    if not isinstance(payload, dict):
        raise AliyunCliCommandError("阿里云 CLI 返回的数据格式错误")
    return payload


def _api_error(payload: dict[str, Any]) -> AliyunApiError:
    code = str(payload.get("Code") or "UnknownError").strip()
    message = str(payload.get("Message") or "阿里云账单查询失败").strip()
    return AliyunApiError(f"{code}: {message}")


async def query_current_cdt_traffic(
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    query_time = now or datetime.now(_SHANGHAI_TZ)
    if query_time.tzinfo is None:
        query_time = query_time.replace(tzinfo=_SHANGHAI_TZ)
    else:
        query_time = query_time.astimezone(_SHANGHAI_TZ)
    billing_cycle = query_time.strftime("%Y-%m")

    all_items: list[dict[str, Any]] = []
    next_token = ""
    seen_tokens: set[str] = set()
    while True:
        arguments = [
            "bssopenapi",
            "DescribeInstanceBill",
            "--BillingCycle",
            billing_cycle,
            "--Granularity",
            "MONTHLY",
            "--ProductCode",
            "cdt",
            "--IsBillingItem",
            "true",
            "--IsHideZeroCharge",
            "false",
            "--MaxResults",
            "300",
        ]
        if next_token:
            arguments.extend(["--NextToken", next_token])

        payload = await _run_aliyun_cli(arguments)
        success = payload.get("Success")
        if success is False or str(success).strip().lower() == "false":
            raise _api_error(payload)

        data = payload.get("Data")
        if not isinstance(data, dict):
            raise AliyunTrafficDataError("阿里云账单响应缺少 Data")
        page_items = data.get("Items")
        if not isinstance(page_items, list):
            raise AliyunTrafficDataError("阿里云账单响应缺少 Items")
        if not all(isinstance(item, dict) for item in page_items):
            raise AliyunTrafficDataError("阿里云账单明细格式错误")
        all_items.extend(page_items)

        next_token = str(data.get("NextToken") or "").strip()
        if not next_token:
            break
        if next_token in seen_tokens:
            raise AliyunTrafficDataError("阿里云账单分页标记重复")
        seen_tokens.add(next_token)

    return build_cdt_traffic_summary(
        all_items,
        billing_cycle=billing_cycle,
        queried_at=query_time.isoformat(timespec="seconds"),
    )
