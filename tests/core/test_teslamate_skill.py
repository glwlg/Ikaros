from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from extension.skills.learned.teslamate.scripts.service import (
    TeslaMateConfig,
    TeslaMateService,
)
from extension.skills.registry import SkillRegistry


class FakeTeslaMateRepository:
    def __init__(self):
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def list_car_status(
        self,
        *,
        car_id: int | None,
        car_name: str,
    ) -> list[dict[str, Any]]:
        self.calls.append(("status", {"car_id": car_id, "car_name": car_name}))
        return [
            {
                "car_id": 1,
                "car_name": "Master Y",
                "model": "Model Y",
                "state": "online",
                "last_seen": datetime(2026, 5, 23, 2, 30, tzinfo=timezone.utc),
                "usable_battery_level": 78,
                "rated_battery_range_km": Decimal("368.4"),
                "ideal_battery_range_km": Decimal("390.0"),
                "odometer": 12345.6,
                "open_charging_process_id": 42,
                "charger_power": 7,
            }
        ]

    def list_drives(
        self,
        *,
        car_id: int | None,
        car_name: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        self.calls.append(
            ("drives", {"car_id": car_id, "car_name": car_name, "limit": limit})
        )
        return [
            {
                "drive_id": 10,
                "car_name": "Master Y",
                "start_date": datetime(2026, 5, 22, 9, 0, tzinfo=timezone.utc),
                "end_date": datetime(2026, 5, 22, 9, 45, tzinfo=timezone.utc),
                "distance": Decimal("31.2"),
                "duration_min": 45,
                "speed_max": 88,
                "start_battery_level": 80,
                "end_battery_level": 74,
                "start_place": "家",
                "end_place": "公司",
            }
        ]

    def list_charges(
        self,
        *,
        car_id: int | None,
        car_name: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        self.calls.append(
            ("charges", {"car_id": car_id, "car_name": car_name, "limit": limit})
        )
        return []

    def summary(
        self,
        *,
        car_id: int | None,
        car_name: str,
        days: int,
    ) -> dict[str, Any]:
        self.calls.append(
            ("summary", {"car_id": car_id, "car_name": car_name, "days": days})
        )
        return {
            "drive_count": 3,
            "distance_km": Decimal("91.8"),
            "duration_min": 128,
            "speed_max": 104,
            "charge_count": 1,
            "charge_energy_added": Decimal("38.4"),
            "charge_energy_used": Decimal("40.1"),
            "cost": Decimal("25.5"),
        }


@pytest.mark.asyncio
async def test_teslamate_status_formats_battery_and_serializes_data():
    repo = FakeTeslaMateRepository()
    result = await TeslaMateService().handle(
        action="battery",
        car_name="Master",
        repository=repo,
    )

    assert result["ok"] is True
    assert result["action"] == "status"
    assert "Master Y" in result["text"]
    assert "78%" in result["text"]
    assert "正在充电" in result["text"]
    assert result["data"]["cars"][0]["rated_battery_range_km"] == 368.4
    assert repo.calls == [("status", {"car_id": None, "car_name": "Master"})]


@pytest.mark.asyncio
async def test_teslamate_drives_clamps_limit_and_formats_route():
    repo = FakeTeslaMateRepository()
    result = await TeslaMateService().handle(
        action="行程",
        car_id=1,
        limit=999,
        repository=repo,
    )

    assert result["ok"] is True
    assert result["action"] == "drives"
    assert "31.2 km" in result["text"]
    assert "家 -> 公司" in result["text"]
    assert repo.calls == [("drives", {"car_id": 1, "car_name": "", "limit": 20})]


@pytest.mark.asyncio
async def test_teslamate_summary_clamps_days():
    repo = FakeTeslaMateRepository()
    result = await TeslaMateService().handle(
        action="stats",
        days=9999,
        repository=repo,
    )

    assert result["ok"] is True
    assert result["action"] == "summary"
    assert "最近 365 天" in result["text"]
    assert "91.8 km" in result["text"]
    assert repo.calls == [("summary", {"car_id": None, "car_name": "", "days": 365})]


@pytest.mark.asyncio
async def test_teslamate_returns_actionable_error_when_unconfigured(monkeypatch):
    for key in [
        "TESLAMATE_DATABASE_URL",
        "TESLAMATE_DB_URL",
        "TESLAMATE_DB_HOST",
        "TESLAMATE_DB_PORT",
        "TESLAMATE_DB_NAME",
        "TESLAMATE_DB_USER",
        "TESLAMATE_DB_PASSWORD",
        "TESLAMATE_DB_SSLMODE",
    ]:
        monkeypatch.delenv(key, raising=False)

    result = await TeslaMateService().handle(action="status")

    assert result["ok"] is False
    assert result["error_code"] == "teslamate_not_configured"
    assert "TESLAMATE_DATABASE_URL" in result["text"]


def test_teslamate_config_supports_url_and_split_env(monkeypatch):
    monkeypatch.setenv(
        "TESLAMATE_DATABASE_URL",
        "postgresql+psycopg://user:pass@db:5432/teslamate",
    )

    assert (
        TeslaMateConfig.from_env().database_url
        == "postgresql://user:pass@db:5432/teslamate"
    )

    monkeypatch.delenv("TESLAMATE_DATABASE_URL", raising=False)
    monkeypatch.setenv("TESLAMATE_DB_HOST", "db")
    monkeypatch.setenv("TESLAMATE_DB_NAME", "teslamate")
    monkeypatch.setenv("TESLAMATE_DB_USER", "readonly")
    monkeypatch.setenv("TESLAMATE_DB_PASSWORD", "p@ss word")

    assert (
        TeslaMateConfig.from_env().database_url
        == "postgresql://readonly:p%40ss%20word@db:5432/teslamate"
    )


def test_teslamate_skill_exports_ikaros_tool():
    registry = SkillRegistry(skills_dir=str(Path("extension/skills")))
    indexed = registry.scan_skills()

    skill = indexed["teslamate"]
    exports = skill["tool_exports"]

    assert exports[0]["name"] == "teslamate_query"
    assert exports[0]["parameters"]["properties"]["action"]["type"] == "string"
    assert "开车" in skill["triggers"]
    assert "去了哪里" in skill["triggers"]
    assert "行驶记录" in skill["triggers"]
    assert "开车去了哪里" in exports[0]["prompt_hint"]
    assert skill["allowed_roles"] == ["ikaros"]
