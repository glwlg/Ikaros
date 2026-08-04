from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.models import User
from api.auth.users import current_active_user
from api.core.database import get_async_session
from api.models.binding import PlatformUserBinding
from core import subscription_store

router = APIRouter()


class SubscriptionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    category: str = Field(default="其他", max_length=60)
    provider: str = Field(default="", max_length=120)
    cost: str = Field(default="", max_length=64)
    start_date: date = Field(default_factory=date.today)
    cycle_months: int = Field(ge=1, le=1200)
    expiry_date: date | None = None
    reminder_enabled: bool = True
    reminder_days_before: int = Field(default=3, ge=0, le=3650)
    delivery_platform: str | None = Field(default=None, max_length=50)
    notes: str = Field(default="", max_length=1000)


class SubscriptionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    category: str | None = Field(default=None, max_length=60)
    provider: str | None = Field(default=None, max_length=120)
    cost: str | None = Field(default=None, max_length=64)
    start_date: date | None = None
    cycle_months: int | None = Field(default=None, ge=1, le=1200)
    expiry_date: date | None = None
    reminder_enabled: bool | None = None
    reminder_days_before: int | None = Field(default=None, ge=0, le=3650)
    delivery_platform: str | None = Field(default=None, max_length=50)
    notes: str | None = Field(default=None, max_length=1000)


async def _user_bindings(
    user_id: int,
    session: AsyncSession,
) -> dict[str, str]:
    result = await session.execute(
        select(PlatformUserBinding).where(PlatformUserBinding.user_id == user_id)
    )
    bindings: dict[str, str] = {}
    for binding in result.scalars().all():
        platform = str(binding.platform or "").strip().lower()
        platform_user_id = str(binding.platform_user_id or "").strip()
        if platform and platform_user_id:
            bindings[platform] = platform_user_id
    return bindings


def _preferred_platform(bindings: dict[str, str]) -> str:
    for platform in ("telegram", "weixin", "dingtalk", "discord"):
        if platform in bindings:
            return platform
    return next(iter(bindings), "")


def _with_delivery_binding(
    payload: dict[str, Any],
    bindings: dict[str, str],
    *,
    use_default: bool,
) -> dict[str, Any]:
    result = dict(payload)
    requested = str(result.pop("delivery_platform", "") or "").strip().lower()
    platform = requested or (_preferred_platform(bindings) if use_default else "")
    if not platform:
        if use_default:
            result["delivery_platform"] = ""
            result["delivery_user_id"] = ""
        return result
    if platform not in bindings:
        raise HTTPException(
            status_code=400,
            detail=f"No {platform} binding found for the current user",
        )
    result["delivery_platform"] = platform
    result["delivery_user_id"] = bindings[platform]
    return result


def _subscription_view(
    row: dict[str, Any], *, today: date | None = None
) -> dict[str, Any]:
    current_date = today or date.today()
    expiry = date.fromisoformat(str(row["expiry_date"]))
    remaining = (expiry - current_date).days
    reminder_on = expiry - timedelta(days=int(row["reminder_days_before"]))
    if remaining < 0:
        status = "expired"
    elif bool(row.get("reminder_enabled")) and current_date >= reminder_on:
        status = "renewal_due"
    else:
        status = "active"
    return {
        key: value
        for key, value in {
            **row,
            "days_remaining": remaining,
            "reminder_date": reminder_on.isoformat(),
            "status": status,
            "delivery_configured": bool(
                row.get("delivery_platform") and row.get("delivery_user_id")
            ),
        }.items()
        if key not in {"owner_user_id", "delivery_user_id"}
    }


@router.get("")
async def get_subscriptions(
    current_user: User = Depends(current_active_user),
):
    rows = await subscription_store.list_subscriptions(current_user.id)
    return [_subscription_view(row) for row in rows]


@router.post("")
async def create_subscription(
    subscription: SubscriptionCreate,
    current_user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    bindings = await _user_bindings(current_user.id, session)
    payload = _with_delivery_binding(
        subscription.model_dump(),
        bindings,
        use_default=True,
    )
    try:
        created = await subscription_store.create_subscription(current_user.id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _subscription_view(created)


@router.put("/{subscription_id}")
async def update_subscription(
    subscription_id: int,
    subscription: SubscriptionUpdate,
    current_user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    current = await subscription_store.get_subscription(
        current_user.id,
        subscription_id,
    )
    if current is None:
        raise HTTPException(status_code=404, detail="Subscription not found")

    payload = subscription.model_dump(exclude_unset=True)
    if "delivery_platform" in payload:
        bindings = await _user_bindings(current_user.id, session)
        payload = _with_delivery_binding(payload, bindings, use_default=False)
    try:
        updated = await subscription_store.update_subscription(
            current_user.id,
            subscription_id,
            payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return _subscription_view(updated)


@router.delete("/{subscription_id}")
async def delete_subscription(
    subscription_id: int,
    current_user: User = Depends(current_active_user),
):
    deleted = await subscription_store.delete_subscription(
        current_user.id,
        subscription_id,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return {"success": True}


__all__ = [
    "SubscriptionCreate",
    "SubscriptionUpdate",
    "create_subscription",
    "delete_subscription",
    "get_subscriptions",
    "router",
    "update_subscription",
]
