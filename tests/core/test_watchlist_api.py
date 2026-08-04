from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api.api.endpoints import watchlist as watchlist_api


@pytest.mark.asyncio
async def test_add_stock_saves_optional_position(monkeypatch):
    captured = {}

    async def fake_resolve(_user, _session):
        return "platform-user"

    async def fake_add(user_id, code, name, platform="telegram"):
        captured["add"] = (user_id, code, name, platform)
        return True

    async def fake_set_position(user_id, code, quantity, cost_price):
        captured["position"] = (user_id, code, quantity, cost_price)
        return True

    monkeypatch.setattr(watchlist_api, "_resolve_platform_uid", fake_resolve)
    monkeypatch.setattr(
        watchlist_api.stock_watch_store, "add_watchlist_stock", fake_add
    )
    monkeypatch.setattr(
        watchlist_api.stock_watch_store,
        "set_watchlist_position",
        fake_set_position,
    )

    result = await watchlist_api.add_stock(
        watchlist_api.StockAdd(
            stock_code=" sh600519 ",
            stock_name=" 贵州茅台 ",
            position_quantity=100,
            cost_price=1500,
        ),
        current_user=SimpleNamespace(id=1),
        session=None,
    )

    assert result == {"success": True}
    assert captured == {
        "add": ("platform-user", "sh600519", "贵州茅台", "telegram"),
        "position": ("platform-user", "sh600519", 100, 1500),
    }


@pytest.mark.asyncio
async def test_update_stock_preserves_existing_position_when_omitted(monkeypatch):
    captured = {}

    async def fake_resolve(_user, _session):
        return "platform-user"

    async def fake_watchlist(_user_id):
        return [
            {
                "stock_code": "sh600519",
                "stock_name": "茅台",
                "platform": "web",
                "position_quantity": 100,
                "cost_price": 1500,
            }
        ]

    async def fake_remove(user_id, code):
        captured["remove"] = (user_id, code)
        return True

    async def fake_add(user_id, code, name, platform="telegram"):
        captured["add"] = (user_id, code, name, platform)
        return True

    async def fake_set_position(user_id, code, quantity, cost_price):
        captured["position"] = (user_id, code, quantity, cost_price)
        return True

    monkeypatch.setattr(watchlist_api, "_resolve_platform_uid", fake_resolve)
    monkeypatch.setattr(
        watchlist_api.stock_watch_store, "get_user_watchlist", fake_watchlist
    )
    monkeypatch.setattr(
        watchlist_api.stock_watch_store,
        "remove_watchlist_stock",
        fake_remove,
    )
    monkeypatch.setattr(
        watchlist_api.stock_watch_store, "add_watchlist_stock", fake_add
    )
    monkeypatch.setattr(
        watchlist_api.stock_watch_store,
        "set_watchlist_position",
        fake_set_position,
    )

    result = await watchlist_api.update_stock(
        "sh600519",
        watchlist_api.StockUpdate(stock_code="sh600519", stock_name="贵州茅台"),
        current_user=SimpleNamespace(id=1),
        session=None,
    )

    assert result == {"success": True}
    assert captured == {
        "remove": ("platform-user", "sh600519"),
        "add": ("platform-user", "sh600519", "贵州茅台", "web"),
        "position": ("platform-user", "sh600519", 100, 1500),
    }


def test_position_fields_must_be_filled_together():
    with pytest.raises(HTTPException) as exc_info:
        watchlist_api._resolve_position_values(100, 0)

    assert exc_info.value.status_code == 400
