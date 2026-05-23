from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Protocol
from urllib.parse import quote, urlencode


class TeslaMateError(Exception):
    """Base TeslaMate skill error."""


class TeslaMateConfigError(TeslaMateError):
    """Raised when the TeslaMate database connection is not configured."""


class TeslaMateDriverError(TeslaMateError):
    """Raised when the PostgreSQL driver is unavailable."""


@dataclass(frozen=True)
class TeslaMateConfig:
    database_url: str
    connect_timeout: int = 5

    @classmethod
    def from_env(cls) -> "TeslaMateConfig":
        raw_url = (
            os.getenv("TESLAMATE_DATABASE_URL")
            or os.getenv("TESLAMATE_DB_URL")
            or ""
        ).strip()
        if raw_url:
            return cls(
                database_url=_normalize_database_url(raw_url),
                connect_timeout=_env_int("TESLAMATE_DB_CONNECT_TIMEOUT", 5),
            )

        keys = {
            "TESLAMATE_DB_HOST",
            "TESLAMATE_DB_PORT",
            "TESLAMATE_DB_NAME",
            "TESLAMATE_DB_USER",
            "TESLAMATE_DB_PASSWORD",
            "TESLAMATE_DB_SSLMODE",
        }
        if not any(os.getenv(key) for key in keys):
            raise TeslaMateConfigError(
                "TeslaMate database is not configured. Set TESLAMATE_DATABASE_URL "
                "or TESLAMATE_DB_HOST/TESLAMATE_DB_USER/TESLAMATE_DB_PASSWORD."
            )

        host = (os.getenv("TESLAMATE_DB_HOST") or "127.0.0.1").strip()
        port = (os.getenv("TESLAMATE_DB_PORT") or "5432").strip()
        name = (os.getenv("TESLAMATE_DB_NAME") or "teslamate").strip()
        user = (os.getenv("TESLAMATE_DB_USER") or "teslamate").strip()
        password = os.getenv("TESLAMATE_DB_PASSWORD") or ""
        sslmode = (os.getenv("TESLAMATE_DB_SSLMODE") or "").strip()

        auth = quote(user, safe="")
        if password:
            auth += f":{quote(password, safe='')}"
        netloc = f"{auth}@{host}"
        if port:
            netloc += f":{port}"
        query = f"?{urlencode({'sslmode': sslmode})}" if sslmode else ""
        return cls(
            database_url=f"postgresql://{netloc}/{quote(name, safe='')}{query}",
            connect_timeout=_env_int("TESLAMATE_DB_CONNECT_TIMEOUT", 5),
        )


class TeslaMateRepository(Protocol):
    def list_car_status(
        self,
        *,
        car_id: int | None,
        car_name: str,
    ) -> list[dict[str, Any]]:
        ...

    def list_drives(
        self,
        *,
        car_id: int | None,
        car_name: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        ...

    def list_charges(
        self,
        *,
        car_id: int | None,
        car_name: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        ...

    def summary(
        self,
        *,
        car_id: int | None,
        car_name: str,
        days: int,
    ) -> dict[str, Any]:
        ...


class PostgresTeslaMateRepository:
    def __init__(self, config: TeslaMateConfig | None = None):
        self.config = config or TeslaMateConfig.from_env()

    def list_car_status(
        self,
        *,
        car_id: int | None,
        car_name: str,
    ) -> list[dict[str, Any]]:
        where, params = _car_where(car_id=car_id, car_name=car_name)
        return self._fetch_all(
            f"""
            SELECT
              c.id AS car_id,
              c.name AS car_name,
              c.model,
              c.trim_badging,
              c.marketing_name,
              c.vin,
              s.state,
              CASE
                WHEN ch.date IS NOT NULL AND (p.date IS NULL OR ch.date >= p.date)
                  THEN ch.date
                ELSE p.date
              END AS last_seen,
              CASE
                WHEN ch.date IS NOT NULL AND (p.date IS NULL OR ch.date >= p.date)
                  THEN ch.battery_level
                ELSE p.battery_level
              END AS battery_level,
              CASE
                WHEN ch.date IS NOT NULL AND (p.date IS NULL OR ch.date >= p.date)
                  THEN ch.usable_battery_level
                ELSE p.usable_battery_level
              END AS usable_battery_level,
              COALESCE(p.rated_battery_range_km, ch.rated_battery_range_km)
                AS rated_battery_range_km,
              COALESCE(p.ideal_battery_range_km, ch.ideal_battery_range_km)
                AS ideal_battery_range_km,
              p.odometer,
              p.latitude,
              p.longitude,
              p.speed,
              p.power,
              p.outside_temp,
              open_cp.id AS open_charging_process_id,
              open_cp.start_date AS charging_start_date,
              ch.charger_power,
              ch.fast_charger_brand,
              ch.fast_charger_type
            FROM cars c
            LEFT JOIN LATERAL (
              SELECT state
              FROM states
              WHERE car_id = c.id
              ORDER BY start_date DESC
              LIMIT 1
            ) s ON TRUE
            LEFT JOIN LATERAL (
              SELECT
                date,
                battery_level,
                usable_battery_level,
                rated_battery_range_km,
                ideal_battery_range_km,
                odometer,
                latitude,
                longitude,
                speed,
                power,
                outside_temp
              FROM positions
              WHERE car_id = c.id
              ORDER BY date DESC
              LIMIT 1
            ) p ON TRUE
            LEFT JOIN LATERAL (
              SELECT
                chg.date,
                chg.battery_level,
                chg.usable_battery_level,
                chg.rated_battery_range_km,
                chg.ideal_battery_range_km,
                chg.charger_power,
                chg.fast_charger_brand,
                chg.fast_charger_type
              FROM charging_processes cp
              JOIN charges chg ON chg.charging_process_id = cp.id
              WHERE cp.car_id = c.id
              ORDER BY chg.date DESC
              LIMIT 1
            ) ch ON TRUE
            LEFT JOIN LATERAL (
              SELECT id, start_date
              FROM charging_processes
              WHERE car_id = c.id AND end_date IS NULL
              ORDER BY start_date DESC
              LIMIT 1
            ) open_cp ON TRUE
            {where}
            ORDER BY COALESCE(c.display_priority, 9999), c.id
            """,
            params,
        )

    def list_drives(
        self,
        *,
        car_id: int | None,
        car_name: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        where, params = _car_where(car_id=car_id, car_name=car_name, alias="c")
        return self._fetch_all(
            f"""
            SELECT
              d.id AS drive_id,
              c.id AS car_id,
              c.name AS car_name,
              d.start_date,
              d.end_date,
              d.distance,
              d.duration_min,
              d.speed_max,
              d.power_max,
              d.outside_temp_avg,
              sp.battery_level AS start_battery_level,
              ep.battery_level AS end_battery_level,
              COALESCE(sgf.name, sa.name, sa.display_name) AS start_place,
              COALESCE(egf.name, ea.name, ea.display_name) AS end_place
            FROM drives d
            JOIN cars c ON c.id = d.car_id
            LEFT JOIN positions sp ON sp.id = d.start_position_id
            LEFT JOIN positions ep ON ep.id = d.end_position_id
            LEFT JOIN addresses sa ON sa.id = d.start_address_id
            LEFT JOIN addresses ea ON ea.id = d.end_address_id
            LEFT JOIN geofences sgf ON sgf.id = d.start_geofence_id
            LEFT JOIN geofences egf ON egf.id = d.end_geofence_id
            {where}
            ORDER BY d.start_date DESC
            LIMIT %s
            """,
            [*params, int(limit)],
        )

    def list_charges(
        self,
        *,
        car_id: int | None,
        car_name: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        where, params = _car_where(car_id=car_id, car_name=car_name, alias="c")
        return self._fetch_all(
            f"""
            SELECT
              cp.id AS charging_process_id,
              c.id AS car_id,
              c.name AS car_name,
              cp.start_date,
              cp.end_date,
              cp.charge_energy_added,
              cp.charge_energy_used,
              cp.start_battery_level,
              COALESCE(cp.end_battery_level, latest_charge.battery_level)
                AS end_battery_level,
              cp.duration_min,
              cp.cost,
              latest_charge.charger_power,
              latest_charge.fast_charger_brand,
              latest_charge.fast_charger_type,
              COALESCE(gf.name, a.name, a.display_name) AS place
            FROM charging_processes cp
            JOIN cars c ON c.id = cp.car_id
            LEFT JOIN addresses a ON a.id = cp.address_id
            LEFT JOIN geofences gf ON gf.id = cp.geofence_id
            LEFT JOIN LATERAL (
              SELECT
                battery_level,
                charger_power,
                fast_charger_brand,
                fast_charger_type
              FROM charges
              WHERE charging_process_id = cp.id
              ORDER BY date DESC
              LIMIT 1
            ) latest_charge ON TRUE
            {where}
            ORDER BY cp.start_date DESC
            LIMIT %s
            """,
            [*params, int(limit)],
        )

    def summary(
        self,
        *,
        car_id: int | None,
        car_name: str,
        days: int,
    ) -> dict[str, Any]:
        where, params = _car_where(car_id=car_id, car_name=car_name, alias="c")
        drive_row = self._fetch_one(
            f"""
            SELECT
              COUNT(d.id) AS drive_count,
              COALESCE(SUM(d.distance), 0) AS distance_km,
              COALESCE(SUM(d.duration_min), 0) AS duration_min,
              COALESCE(MAX(d.speed_max), 0) AS speed_max
            FROM drives d
            JOIN cars c ON c.id = d.car_id
            {where}
              {_where_conjunction(where)} d.start_date >=
                (now() AT TIME ZONE 'UTC') - (%s * interval '1 day')
            """,
            [*params, int(days)],
        )
        charge_row = self._fetch_one(
            f"""
            SELECT
              COUNT(cp.id) AS charge_count,
              COALESCE(SUM(cp.charge_energy_added), 0) AS charge_energy_added,
              COALESCE(SUM(cp.charge_energy_used), 0) AS charge_energy_used,
              COALESCE(SUM(cp.cost), 0) AS cost
            FROM charging_processes cp
            JOIN cars c ON c.id = cp.car_id
            {where}
              {_where_conjunction(where)} cp.start_date >=
                (now() AT TIME ZONE 'UTC') - (%s * interval '1 day')
            """,
            [*params, int(days)],
        )
        return {**dict(drive_row or {}), **dict(charge_row or {}), "days": days}

    def _fetch_all(self, query: str, params: list[Any]) -> list[dict[str, Any]]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                return [dict(row) for row in cur.fetchall()]

    def _fetch_one(self, query: str, params: list[Any]) -> dict[str, Any]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                row = cur.fetchone()
                return dict(row or {})

    def _connect(self):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise TeslaMateDriverError(
                "Python package psycopg is required for TeslaMate PostgreSQL access."
            ) from exc

        return psycopg.connect(
            self.config.database_url,
            connect_timeout=self.config.connect_timeout,
            row_factory=dict_row,
        )


class TeslaMateService:
    async def handle(
        self,
        *,
        action: str,
        car_id: int | None = None,
        car_name: str = "",
        limit: int = 5,
        days: int = 30,
        repository: TeslaMateRepository | None = None,
    ) -> dict[str, Any]:
        safe_action = _normalize_action(action)
        safe_limit = _clamp_int(limit, default=5, minimum=1, maximum=20)
        safe_days = _clamp_int(days, default=30, minimum=1, maximum=365)

        try:
            repo = repository or PostgresTeslaMateRepository()
            if safe_action == "status":
                rows = await asyncio.to_thread(
                    repo.list_car_status,
                    car_id=car_id,
                    car_name=car_name,
                )
                return _ok(
                    text=_format_status(rows),
                    action=safe_action,
                    data={"cars": _json_rows(rows)},
                )
            if safe_action == "drives":
                rows = await asyncio.to_thread(
                    repo.list_drives,
                    car_id=car_id,
                    car_name=car_name,
                    limit=safe_limit,
                )
                return _ok(
                    text=_format_drives(rows, limit=safe_limit),
                    action=safe_action,
                    data={"drives": _json_rows(rows), "limit": safe_limit},
                )
            if safe_action == "charges":
                rows = await asyncio.to_thread(
                    repo.list_charges,
                    car_id=car_id,
                    car_name=car_name,
                    limit=safe_limit,
                )
                return _ok(
                    text=_format_charges(rows, limit=safe_limit),
                    action=safe_action,
                    data={"charges": _json_rows(rows), "limit": safe_limit},
                )
            if safe_action == "summary":
                row = await asyncio.to_thread(
                    repo.summary,
                    car_id=car_id,
                    car_name=car_name,
                    days=safe_days,
                )
                return _ok(
                    text=_format_summary(row, days=safe_days),
                    action=safe_action,
                    data={"summary": _json_row(row)},
                )
        except TeslaMateConfigError as exc:
            return _error(
                "teslamate_not_configured",
                str(exc),
                (
                    "TeslaMate 还没配置数据库连接。请设置 "
                    "`TESLAMATE_DATABASE_URL=postgresql://user:password@host:5432/teslamate`，"
                    "或设置 `TESLAMATE_DB_HOST`、`TESLAMATE_DB_USER`、"
                    "`TESLAMATE_DB_PASSWORD`、`TESLAMATE_DB_NAME`。"
                ),
            )
        except TeslaMateDriverError as exc:
            return _error(
                "teslamate_driver_missing",
                str(exc),
                "缺少 PostgreSQL 驱动 `psycopg`，请同步依赖后再试。",
            )
        except Exception as exc:
            return _error(
                "teslamate_query_failed",
                str(exc),
                f"查询 TeslaMate 失败：{exc}",
            )

        return _error(
            "unsupported_action",
            f"Unsupported TeslaMate action: {action}",
            "不支持的 TeslaMate 操作。可用操作：`status`、`drives`、`charges`、`summary`。",
        )


teslamate_service = TeslaMateService()


def _normalize_database_url(raw_url: str) -> str:
    text = str(raw_url or "").strip()
    if text.startswith("postgresql+psycopg://"):
        return "postgresql://" + text.removeprefix("postgresql+psycopg://")
    if text.startswith("postgresql+asyncpg://"):
        return "postgresql://" + text.removeprefix("postgresql+asyncpg://")
    return text


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)) or default)
    except Exception:
        return default


def _clamp_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(default if value is None or value == "" else value)
    except Exception:
        number = default
    return max(minimum, min(number, maximum))


def _normalize_action(action: str) -> str:
    token = str(action or "").strip().lower()
    action_map = {
        "": "status",
        "battery": "status",
        "car": "status",
        "cars": "status",
        "status": "status",
        "state": "status",
        "电量": "status",
        "车况": "status",
        "状态": "status",
        "drive": "drives",
        "drives": "drives",
        "trip": "drives",
        "trips": "drives",
        "行程": "drives",
        "驾驶": "drives",
        "charge": "charges",
        "charges": "charges",
        "charging": "charges",
        "充电": "charges",
        "summary": "summary",
        "overview": "summary",
        "stats": "summary",
        "统计": "summary",
        "概览": "summary",
    }
    return action_map.get(token, token)


def _car_where(
    *,
    car_id: int | None,
    car_name: str,
    alias: str = "c",
) -> tuple[str, list[Any]]:
    prefix = f"{alias}." if alias else ""
    params: list[Any] = []
    if car_id is not None:
        params.append(int(car_id))
        return f"WHERE {prefix}id = %s", params
    name = str(car_name or "").strip()
    if name:
        like = f"%{name}%"
        params.extend([like, like, like])
        return (
            f"WHERE ({prefix}name ILIKE %s OR {prefix}vin ILIKE %s "
            f"OR {prefix}model ILIKE %s)",
            params,
        )
    return "", params


def _where_conjunction(where_clause: str) -> str:
    return "AND" if str(where_clause or "").strip() else "WHERE"


def _ok(*, text: str, action: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, "action": action, "text": text, "data": data}


def _error(error_code: str, message: str, text: str) -> dict[str, Any]:
    return {
        "ok": False,
        "error_code": error_code,
        "message": message,
        "text": text,
        "failure_mode": "recoverable",
    }


def _format_status(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "TeslaMate 里没有匹配的车辆。"

    lines = ["TeslaMate 车辆状态："]
    for row in rows:
        name = _car_label(row)
        state = str(row.get("state") or "unknown")
        battery = _percent(row.get("usable_battery_level") or row.get("battery_level"))
        rated = _km(row.get("rated_battery_range_km"))
        ideal = _km(row.get("ideal_battery_range_km"))
        odometer = _km(row.get("odometer"))
        last_seen = _format_dt(row.get("last_seen"))
        charging = "，正在充电" if row.get("open_charging_process_id") else ""
        charger_power = _number(row.get("charger_power"), digits=0)
        power_text = f"，最近充电功率 {charger_power} kW" if charger_power else ""
        range_parts = [
            item
            for item in [
                f"Rated {rated}" if rated else "",
                f"Ideal {ideal}" if ideal else "",
            ]
            if item
        ]
        range_text = f"，续航 {' / '.join(range_parts)}" if range_parts else ""
        odometer_text = f"，里程 {odometer}" if odometer else ""
        lines.append(
            f"- {name}: {battery or '电量未知'}，状态 {state}{charging}{range_text}"
            f"{odometer_text}{power_text}，最后更新 {last_seen or '未知'}"
        )
    return "\n".join(lines)


def _format_drives(rows: list[dict[str, Any]], *, limit: int) -> str:
    if not rows:
        return "TeslaMate 里没有匹配的行程记录。"

    lines = [f"最近 {min(limit, len(rows))} 条 TeslaMate 行程："]
    for row in rows:
        start = _format_dt(row.get("start_date"))
        end = _format_dt(row.get("end_date")) or "进行中"
        distance = _km(row.get("distance"))
        duration = _duration(row.get("duration_min"))
        battery = _battery_delta(row)
        place = _place_route(row)
        speed = _number(row.get("speed_max"), digits=0)
        speed_text = f"，最高 {speed} km/h" if speed else ""
        lines.append(
            f"- {row.get('car_name') or '车辆'}: {start} -> {end}，{distance or '距离未知'}"
            f"，{duration or '时长未知'}{battery}{speed_text}{place}"
        )
    return "\n".join(lines)


def _format_charges(rows: list[dict[str, Any]], *, limit: int) -> str:
    if not rows:
        return "TeslaMate 里没有匹配的充电记录。"

    lines = [f"最近 {min(limit, len(rows))} 条 TeslaMate 充电记录："]
    for row in rows:
        start = _format_dt(row.get("start_date"))
        end = _format_dt(row.get("end_date")) or "进行中"
        energy = _kwh(row.get("charge_energy_added"))
        used = _kwh(row.get("charge_energy_used"))
        duration = _duration(row.get("duration_min"))
        cost = _money(row.get("cost"))
        battery = _battery_delta(row)
        place = str(row.get("place") or "").strip()
        place_text = f"，地点 {place}" if place else ""
        cost_text = f"，费用 {cost}" if cost else ""
        used_text = f"，消耗 {used}" if used else ""
        lines.append(
            f"- {row.get('car_name') or '车辆'}: {start} -> {end}，增加 {energy or '未知'}"
            f"{used_text}，{duration or '时长未知'}{battery}{cost_text}{place_text}"
        )
    return "\n".join(lines)


def _format_summary(row: dict[str, Any], *, days: int) -> str:
    drive_count = int(row.get("drive_count") or 0)
    charge_count = int(row.get("charge_count") or 0)
    distance = _km(row.get("distance_km")) or "0 km"
    duration = _duration(row.get("duration_min")) or "0 分钟"
    energy = _kwh(row.get("charge_energy_added")) or "0 kWh"
    used = _kwh(row.get("charge_energy_used")) or "0 kWh"
    cost = _money(row.get("cost"))
    speed = _number(row.get("speed_max"), digits=0)
    speed_text = f"\n- 最高车速：{speed} km/h" if speed else ""
    cost_text = f"\n- 充电费用：{cost}" if cost else ""
    return (
        f"最近 {days} 天 TeslaMate 概览：\n"
        f"- 行程：{drive_count} 次，{distance}，驾驶 {duration}\n"
        f"- 充电：{charge_count} 次，增加 {energy}，消耗 {used}"
        f"{cost_text}{speed_text}"
    )


def _car_label(row: dict[str, Any]) -> str:
    name = str(row.get("car_name") or "").strip()
    model = str(row.get("marketing_name") or row.get("model") or "").strip()
    if name and model and model.lower() not in name.lower():
        return f"{name} ({model})"
    return name or model or f"car#{row.get('car_id')}"


def _place_route(row: dict[str, Any]) -> str:
    start = str(row.get("start_place") or "").strip()
    end = str(row.get("end_place") or "").strip()
    if start and end:
        return f"，{start} -> {end}"
    if start:
        return f"，从 {start} 出发"
    if end:
        return f"，到 {end}"
    return ""


def _battery_delta(row: dict[str, Any]) -> str:
    start = row.get("start_battery_level")
    end = row.get("end_battery_level")
    if start is None and end is None:
        return ""
    if start is not None and end is not None:
        return f"，电量 {start}% -> {end}%"
    if start is not None:
        return f"，起始电量 {start}%"
    return f"，结束电量 {end}%"


def _format_dt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value))
        except Exception:
            return str(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().strftime("%Y-%m-%d %H:%M")


def _number(value: Any, *, digits: int = 1) -> str:
    if value is None:
        return ""
    try:
        number = float(value)
    except Exception:
        return ""
    if digits <= 0:
        return str(int(round(number)))
    return f"{number:.{digits}f}".rstrip("0").rstrip(".")


def _percent(value: Any) -> str:
    number = _number(value, digits=0)
    return f"{number}%" if number else ""


def _km(value: Any) -> str:
    number = _number(value, digits=1)
    return f"{number} km" if number else ""


def _kwh(value: Any) -> str:
    number = _number(value, digits=1)
    return f"{number} kWh" if number else ""


def _money(value: Any) -> str:
    number = _number(value, digits=2)
    return number if number else ""


def _duration(value: Any) -> str:
    if value is None:
        return ""
    try:
        minutes = int(round(float(value)))
    except Exception:
        return ""
    if minutes < 60:
        return f"{minutes} 分钟"
    hours = minutes // 60
    rest = minutes % 60
    if rest:
        return f"{hours} 小时 {rest} 分钟"
    return f"{hours} 小时"


def _json_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_json_row(row) for row in rows]


def _json_row(row: dict[str, Any]) -> dict[str, Any]:
    return {str(key): _json_value(value) for key, value in dict(row or {}).items()}


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value
