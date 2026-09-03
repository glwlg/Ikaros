from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from api.services import aliyun_traffic


def test_build_cdt_traffic_summary_aggregates_usage_and_remaining_quota():
    summary = aliyun_traffic.build_cdt_traffic_summary(
        [
            {
                "BillingItem": "公网流量",
                "BillingItemCode": "cdt_internet_flow",
                "Region": "cn-hangzhou",
                "Usage": "8.5",
                "UsageUnit": "GB",
            },
            {
                "BillingItem": "公网流量",
                "BillingItemCode": "cdt_internet_flow",
                "Region": "cn-hangzhou",
                "Usage": "1024",
                "UsageUnit": "MB",
            },
            {
                "BillingItem": "公网流量",
                "BillingItemCode": "cdt_internet_flow",
                "Region": "cn-shanghai",
                "Usage": "512",
                "UsageUnit": "MB",
            },
        ],
        billing_cycle="2026-08",
        queried_at="2026-08-26T12:00:00+08:00",
    )

    assert summary == {
        "billing_cycle": "2026-08",
        "quota_gb": 20.0,
        "used_gb": 10.0,
        "remaining_gb": 10.0,
        "overage_gb": 0.0,
        "usage_percent": 50.0,
        "queried_at": "2026-08-26T12:00:00+08:00",
        "items": [
            {
                "billing_item": "公网流量",
                "billing_item_code": "cdt_internet_flow",
                "region": "cn-hangzhou",
                "usage_gb": 9.5,
            },
            {
                "billing_item": "公网流量",
                "billing_item_code": "cdt_internet_flow",
                "region": "cn-shanghai",
                "usage_gb": 0.5,
            },
        ],
    }


def test_build_cdt_traffic_summary_reports_overage():
    summary = aliyun_traffic.build_cdt_traffic_summary(
        [{"Usage": "22.25", "UsageUnit": "GB"}],
        billing_cycle="2026-08",
        queried_at="2026-08-26T12:00:00+08:00",
    )

    assert summary["used_gb"] == 22.25
    assert summary["remaining_gb"] == 0.0
    assert summary["overage_gb"] == 2.25
    assert summary["usage_percent"] == 111.25


def test_build_cdt_traffic_summary_rejects_non_traffic_units():
    with pytest.raises(aliyun_traffic.AliyunTrafficDataError, match="Hour"):
        aliyun_traffic.build_cdt_traffic_summary(
            [{"Usage": "3", "UsageUnit": "Hour"}],
            billing_cycle="2026-08",
        )


@pytest.mark.asyncio
async def test_query_current_cdt_traffic_uses_describe_api_and_paginates(
    monkeypatch,
):
    calls: list[list[str]] = []

    async def fake_run_cli(arguments: list[str]):
        calls.append(arguments)
        if "--NextToken" not in arguments:
            return {
                "Success": True,
                "Data": {
                    "BillingCycle": "2026-08",
                    "Items": [{"Usage": "4", "UsageUnit": "GB"}],
                    "NextToken": "next-page",
                },
            }
        return {
            "Success": True,
            "Data": {
                "BillingCycle": "2026-08",
                "Items": [{"Usage": "1.5", "UsageUnit": "GB"}],
                "NextToken": "",
            },
        }

    monkeypatch.setattr(aliyun_traffic, "_run_aliyun_cli", fake_run_cli)

    summary = await aliyun_traffic.query_current_cdt_traffic(
        now=datetime(2026, 8, 26, 10, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    )

    assert summary["billing_cycle"] == "2026-08"
    assert summary["used_gb"] == 5.5
    assert summary["remaining_gb"] == 14.5
    assert len(calls) == 2
    assert calls[0][:2] == ["bssopenapi", "DescribeInstanceBill"]
    assert calls[0][calls[0].index("--ProductCode") + 1] == "cdt"
    assert calls[0][calls[0].index("--IsBillingItem") + 1] == "true"
    assert calls[0][calls[0].index("--IsHideZeroCharge") + 1] == "false"
    assert calls[1][calls[1].index("--NextToken") + 1] == "next-page"


@pytest.mark.asyncio
async def test_query_current_cdt_traffic_rejects_failed_api_response(monkeypatch):
    async def fake_run_cli(_arguments: list[str]):
        return {
            "Success": False,
            "Code": "Forbidden.RAM",
            "Message": "You are not authorized to do this action.",
        }

    monkeypatch.setattr(aliyun_traffic, "_run_aliyun_cli", fake_run_cli)

    with pytest.raises(aliyun_traffic.AliyunApiError, match="Forbidden.RAM"):
        await aliyun_traffic.query_current_cdt_traffic()
