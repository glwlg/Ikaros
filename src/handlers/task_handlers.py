from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from core.channel_runtime_store import channel_runtime_store
from core.artifact_ledger import get_artifact_ledger
from core.config import ikaros_kernel_provider
from core.heartbeat_store import heartbeat_store
from core.platform.models import UnifiedContext
from core.platform.registry import adapter_manager
from core.runtime_quality_report import build_task_quality_report
from core.runtime_v2 import TERMINAL_STATUSES, runtime_v2
from core.skill_menu import (
    cache_items,
    get_cached_item,
    make_callback,
    menu_store,
    parse_callback,
)
from core.task_confirmation import (
    clear_expired_waiting_confirmation,
    is_confirmation_expired,
)
from core.task_inbox import task_inbox

from .base_handlers import (
    check_permission_unified,
    edit_callback_message,
    get_effective_user_id,
)

TASK_MENU_NS = "taskm"
logger = logging.getLogger(__name__)
_TASK_ACTION_REFS_KEY = "__task_action_refs__"


def _parse_subcommand(text: str) -> tuple[str, str]:
    raw = (text or "").strip()
    if not raw:
        return "recent", ""
    parts = raw.split(maxsplit=2)
    if not parts or not parts[0].startswith("/task"):
        return "recent", ""
    if len(parts) == 1:
        return "recent", ""
    cmd = parts[1].strip().lower()
    args = parts[2].strip() if len(parts) >= 3 else ""
    return cmd, args


def _compact(text: Any, limit: int = 48) -> str:
    raw = str(text or "").strip().replace("\n", " ")
    if len(raw) <= limit:
        return raw
    return raw[: max(0, limit - 1)] + "…"


def _should_show_task(item: Any) -> bool:
    source = str(getattr(item, "source", "") or "").strip().lower()
    if source != "heartbeat":
        return True
    status = str(getattr(item, "status", "") or "").strip().lower()
    return status == "waiting_external"


def _runtime_v2_task_to_item(row: dict[str, Any]) -> Any:
    metadata = dict(row.get("metadata") or {})
    source = (
        str(metadata.get("source") or "").strip()
        or str(row.get("turn_source") or "").strip()
        or str(row.get("session_kind") or "").strip()
        or "runtime_v2"
    )
    metadata.update(
        {
            "runtime_v2": True,
            "runtime_v2_session_id": str(row.get("session_id") or "").strip(),
            "runtime_v2_turn_id": str(row.get("turn_id") or "").strip(),
            "runtime_v2_turn_status": str(row.get("turn_status") or "").strip(),
            "kernel_provider": str(row.get("kernel_provider") or "").strip()
            or str(metadata.get("kernel_provider") or "").strip(),
            "platform": str(row.get("platform") or "").strip(),
        }
    )
    return SimpleNamespace(
        task_id=str(row.get("id") or "").strip(),
        source=source,
        goal=str(row.get("goal") or "").strip()
        or str(row.get("turn_input_text") or "").strip(),
        user_id=str(row.get("platform_user_id") or "").strip(),
        status=str(row.get("status") or "").strip(),
        updated_at=str(row.get("updated_at") or "").strip(),
        created_at=str(row.get("created_at") or "").strip(),
        metadata=metadata,
        result={},
        output={},
        final_output="",
        events=[],
    )


def _runtime_v2_task_items(user_id: str, *, open_only: bool) -> list[Any]:
    statuses: list[str] = []
    if open_only:
        statuses = [
            status
            for status in (
                "queued",
                "running",
                "waiting_user",
                "waiting_external",
            )
            if status not in TERMINAL_STATUSES
        ]
    rows = runtime_v2.list_tasks_for_user(
        platform_user_id=user_id,
        statuses=statuses,
        limit=30,
    )
    return [_runtime_v2_task_to_item(row) for row in rows]


def _runtime_v2_legacy_task_ids(items: list[Any]) -> set[str]:
    ids: set[str] = set()
    for item in items:
        metadata = dict(getattr(item, "metadata", {}) or {})
        legacy_id = str(metadata.get("task_inbox_id") or "").strip()
        if legacy_id:
            ids.add(legacy_id)
    return ids


def _task_usage_text() -> str:
    return "用法: `/task`、`/task recent`、`/task open` 或 `/task diag`"


def _artifact_delivery_summary(events: Any) -> str:
    delivered = 0
    failed = 0
    for item in list(events or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("event") or "").strip() != "artifact_delivery":
            continue
        extra = item.get("extra")
        if not isinstance(extra, dict):
            continue
        delivered += len(extra.get("delivered") or [])
        failed += len(extra.get("failed") or [])
    if not delivered and not failed:
        return ""
    return f"delivered={delivered}; failed={failed}"


def _artifact_ledger_summary(user_data: dict[str, Any] | None) -> str:
    delivered = 0
    failed = 0
    pending = 0
    for item in get_artifact_ledger(user_data):
        status = str(item.get("status") or "").strip().lower()
        if status == "delivered":
            delivered += 1
        elif status == "failed":
            failed += 1
        else:
            pending += 1
    if not delivered and not failed and not pending:
        return "none"
    return f"delivered={delivered}; failed={failed}; pending={pending}"


def _channel_adapters_summary() -> str:
    adapters = getattr(adapter_manager, "_adapters", None)
    if not isinstance(adapters, dict) or not adapters:
        return "none"

    parts: list[str] = []
    for name, adapter in sorted(adapters.items(), key=lambda item: str(item[0])):
        capabilities = getattr(adapter, "capabilities", None)
        flags: list[str] = []
        if capabilities is not None:
            flags.append("edit" if bool(getattr(capabilities, "edit_message", False)) else "no-edit")
            media = [
                kind
                for kind in ("photo", "video", "audio", "document")
                if bool(capabilities.supports_reply_kind(kind))
            ]
            flags.append("+".join(media) if media else "no-media")
        else:
            flags.append("edit" if bool(getattr(adapter, "can_update_message", False)) else "no-edit")
        parts.append(f"{str(name)}({'; '.join(flags)})")

    return "; ".join(parts[:12])


def _cache_task_action_ref(
    ctx: UnifiedContext,
    *,
    view: str,
    index: str | int | None,
    task_id: str,
) -> str:
    token = uuid4().hex[:12]
    store = menu_store(ctx, TASK_MENU_NS)
    refs = store.setdefault(_TASK_ACTION_REFS_KEY, {})
    if not isinstance(refs, dict):
        refs = {}
        store[_TASK_ACTION_REFS_KEY] = refs
    refs[token] = {
        "view": str(view or "").strip() or "recent",
        "index": str(index if index is not None else "").strip(),
        "task_id": str(task_id or "").strip(),
    }
    if len(refs) > 128:
        stale_tokens = list(refs.keys())[:-64]
        for stale_token in stale_tokens:
            refs.pop(stale_token, None)
    return token


def _resolve_task_action_ref(
    ctx: UnifiedContext,
    token: str | None,
) -> tuple[str, str, str]:
    raw_token = str(token or "").strip()
    if not raw_token:
        return "", "", ""
    store = menu_store(ctx, TASK_MENU_NS)
    refs = store.get(_TASK_ACTION_REFS_KEY, {})
    if not isinstance(refs, dict):
        return "", "", ""
    payload = refs.get(raw_token)
    if not isinstance(payload, dict):
        return "", "", ""
    return (
        str(payload.get("view") or "").strip(),
        str(payload.get("index") or "").strip(),
        str(payload.get("task_id") or "").strip(),
    )


async def _active_confirmation_row(user_id: str) -> list[dict[str, str]]:
    active_task = channel_runtime_store.get_active_task(platform_user_id=user_id)
    if not active_task:
        active_task = await heartbeat_store.get_session_active_task(user_id)
    if not active_task or str(active_task.get("status") or "") != "waiting_user":
        return []
    if is_confirmation_expired(active_task):
        await clear_expired_waiting_confirmation(
            user_id=user_id,
            active_task=active_task,
        )
        return []
    return [
        {"text": "继续当前任务", "callback_data": "task_continue"},
        {"text": "停止当前任务", "callback_data": "task_stop"},
    ]


async def _build_task_list_payload(
    ctx: UnifiedContext,
    *,
    view: str = "recent",
    page: int = 0,
    prefix: str = "",
) -> tuple[str, dict]:
    user_id = get_effective_user_id(ctx)
    normalized_view = "open" if str(view or "").strip().lower() == "open" else "recent"
    runtime_rows = _runtime_v2_task_items(
        user_id,
        open_only=normalized_view == "open",
    )
    legacy_ids = _runtime_v2_legacy_task_ids(runtime_rows)
    if normalized_view == "open":
        rows = await task_inbox.list_open(user_id=user_id, limit=30)
        title = "🧾 未完成任务"
    else:
        rows = await task_inbox.list_recent(user_id=user_id, limit=30)
        title = "🧾 最近 10 个任务"
    rows = [
        *runtime_rows,
        *[
            row
            for row in rows
            if str(getattr(row, "task_id", "") or "").strip() not in legacy_ids
        ],
    ]
    rows = [row for row in rows if _should_show_task(row)]
    cache_items(ctx, TASK_MENU_NS, normalized_view, rows)

    actions: list[list[dict[str, str]]] = []
    confirm_row = await _active_confirmation_row(user_id)
    if confirm_row:
        actions.append(confirm_row)

    if not rows:
        if prefix:
            title = f"{prefix}\n\n{title}"
        actions.append(
            [
                {"text": "最近任务", "callback_data": make_callback(TASK_MENU_NS, "recent", 0)},
                {"text": "未完成任务", "callback_data": make_callback(TASK_MENU_NS, "open", 0)},
            ]
        )
        return f"{title}\n\n当前没有 ikaros 任务记录。", {"actions": actions}

    page_size = 10
    total_pages = max(1, (len(rows) + page_size - 1) // page_size)
    current_page = max(0, min(int(page or 0), total_pages - 1))
    start = current_page * page_size
    items = rows[start : start + page_size]

    lines: list[str] = []
    if prefix:
        lines.extend([prefix.strip(), ""])
    lines.extend([f"{title}（第 {current_page + 1}/{total_pages} 页）"])
    for absolute_index, item in enumerate(items, start=start):
        metadata = dict(item.metadata or {}) if isinstance(item.metadata, dict) else {}
        kernel_provider = str(metadata.get("kernel_provider") or "").strip()
        kernel_text = f" | kernel:{kernel_provider}" if kernel_provider else ""
        lines.append(
            f"- `{item.task_id}` | {item.status} | {item.source}{kernel_text} | {_compact(item.goal, 36)}"
        )
        followup = dict(metadata.get("followup") or {}) if isinstance(metadata.get("followup"), dict) else {}
        refs = dict(followup.get("refs") or {}) if isinstance(followup.get("refs"), dict) else {}
        done_when = str(followup.get("done_when") or "").strip()
        if done_when:
            lines.append(f"  done_when: {done_when}")
        pr_url = str(refs.get("pr_url") or "").strip()
        if pr_url:
            lines.append(f"  pr: {pr_url}")

    for absolute_index, item in enumerate(items, start=start):
        actions.append(
            [
                {
                    "text": f"{item.status} | {_compact(item.goal, 18)}",
                    "callback_data": make_callback(TASK_MENU_NS, "show", normalized_view, absolute_index),
                }
            ]
        )

    nav_row = []
    if current_page > 0:
        nav_row.append(
            {"text": "⬅️ 上一页", "callback_data": make_callback(TASK_MENU_NS, normalized_view, current_page - 1)}
        )
    if current_page < total_pages - 1:
        nav_row.append(
            {"text": "➡️ 下一页", "callback_data": make_callback(TASK_MENU_NS, normalized_view, current_page + 1)}
        )
    if nav_row:
        actions.append(nav_row)
    actions.append(
        [
            {"text": "最近任务", "callback_data": make_callback(TASK_MENU_NS, "recent", 0)},
            {"text": "未完成任务", "callback_data": make_callback(TASK_MENU_NS, "open", 0)},
        ]
    )
    return "\n".join(lines), {"actions": actions}


async def _build_task_diag_payload(ctx: UnifiedContext) -> str:
    user_id = get_effective_user_id(ctx)
    message = getattr(ctx, "message", None)
    platform = str(getattr(message, "platform", "") or "").strip().lower()
    chat_id = str(getattr(getattr(message, "chat", None), "id", "") or "").strip()
    session_id = channel_runtime_store.get_session_id(
        platform=platform,
        platform_user_id=user_id,
    )
    channel_active = channel_runtime_store.get_active_task(
        platform=platform,
        platform_user_id=user_id,
    )
    heartbeat_active = await heartbeat_store.get_session_active_task(user_id)
    heartbeat_state = await heartbeat_store.get_state(user_id)
    status = dict(heartbeat_state.get("status") or {})
    delivery = dict(status.get("delivery") or {})
    last_error = str(status.get("last_error") or "").strip()
    open_rows = await task_inbox.list_open(user_id=user_id, limit=0)
    recent_rows = await task_inbox.list_recent(user_id=user_id, limit=30)
    runtime_task_rows = runtime_v2.list_tasks_for_user(
        platform_user_id=user_id,
        limit=200,
    )
    runtime_open_count = sum(
        1
        for row in runtime_task_rows
        if str(row.get("status") or "").strip() not in TERMINAL_STATUSES
    )
    quality = build_task_quality_report(recent_rows)

    def _active_line(name: str, task: dict[str, Any] | None) -> str:
        if not isinstance(task, dict) or not str(task.get("id") or "").strip():
            return f"- {name} active：none"
        return (
            f"- {name} active：`{str(task.get('id') or '').strip()}` "
            f"| {str(task.get('status') or '').strip() or 'unknown'} "
            f"| kernel:{str(task.get('kernel_provider') or '').strip() or '-'}"
        )

    lines = [
        "🧪 Ikaros 运行诊断",
        "",
        f"- Kernel：`{ikaros_kernel_provider()}`",
        f"- Platform：`{platform or '-'}`",
        f"- User：`{user_id}`",
        f"- Chat：`{chat_id or '-'}`",
        f"- Session：`{session_id or '-'}`",
        f"- Channels：{_channel_adapters_summary()}",
        _active_line("channel", channel_active),
        _active_line("heartbeat", heartbeat_active),
        f"- TaskInbox：open={len(open_rows)}; recent={len(recent_rows)}",
        f"- Runtime v2 tasks：open={runtime_open_count}; recent={len(runtime_task_rows)}",
        f"- Artifact ledger：{_artifact_ledger_summary(getattr(ctx, 'user_data', None))}",
        f"- 近期质量：failed={quality['status_counts'].get('failed', 0)}; "
        f"artifact_failed={quality['artifact_failed']}",
        f"- Delivery target：{str(delivery.get('last_platform') or '-')}"
        f":{str(delivery.get('last_chat_id') or '-')}",
    ]
    if last_error:
        lines.append(f"- Last error：{_compact(last_error, 120)}")
    recommendations = list(quality.get("recommendations") or [])
    if recommendations:
        lines.append(f"- 建议：{_compact(recommendations[0], 120)}")
    return "\n".join(lines)


async def _build_task_detail_payload(
    ctx: UnifiedContext,
    *,
    view: str,
    index: str | int | None,
) -> tuple[str, dict]:
    item = get_cached_item(ctx, TASK_MENU_NS, view, index)
    if item is None:
        return await _build_task_list_payload(
            ctx,
            view=view,
            prefix="❌ 任务列表已过期，请重新选择。",
        )

    metadata = dict(item.metadata or {}) if isinstance(item.metadata, dict) else {}
    followup = metadata.get("followup")
    followup_obj = dict(followup) if isinstance(followup, dict) else {}
    refs = dict(followup_obj.get("refs") or {}) if isinstance(followup_obj.get("refs"), dict) else {}
    lines = [
        f"🧾 任务详情：`{item.task_id}`",
        "",
        f"- 状态：`{item.status}`",
        f"- 来源：`{item.source}`",
        f"- 更新时间：`{item.updated_at}`",
        f"- 目标：{str(item.goal or '').strip()}",
    ]
    kernel_provider = str(metadata.get("kernel_provider") or "").strip()
    if kernel_provider:
        lines.append(f"- Kernel：`{kernel_provider}`")
    kernel_status = str(metadata.get("kernel_status") or "").strip()
    if kernel_status:
        lines.append(f"- Kernel 状态：`{kernel_status}`")
    if followup_obj:
        lines.append(f"- Follow-up：{str(followup_obj.get('done_when') or '').strip()}")
    if refs.get("pr_url"):
        lines.append(f"- PR：{refs.get('pr_url')}")
    if getattr(item, "result", None):
        lines.append(f"- Result：{_compact(getattr(item, 'result'), 80)}")
    if getattr(item, "output", None):
        lines.append(f"- Output：{_compact(getattr(item, 'output'), 80)}")
    artifact_summary = _artifact_delivery_summary(getattr(item, "events", []))
    if artifact_summary:
        lines.append(f"- 附件投递：`{artifact_summary}`")

    delete_token = _cache_task_action_ref(
        ctx,
        view=view,
        index=index,
        task_id=item.task_id,
    )

    return "\n".join(lines), {
        "actions": [
            [
                {
                    "text": "🗑️ 删除任务",
                    "callback_data": make_callback(TASK_MENU_NS, "delete", delete_token),
                },
                {"text": "返回列表", "callback_data": make_callback(TASK_MENU_NS, view, 0)},
            ]
        ]
    }


async def _build_task_delete_confirm_payload(
    ctx: UnifiedContext,
    *,
    view: str,
    index: str | int | None,
    task_id: str,
) -> tuple[str, dict]:
    item = get_cached_item(ctx, TASK_MENU_NS, view, index)
    if item is None and str(task_id or "").strip():
        item = await task_inbox.get(str(task_id or "").strip())
    if item is None and str(task_id or "").strip():
        runtime_task = runtime_v2.get_task(str(task_id or "").strip())
        if runtime_task:
            session = runtime_v2.get_session(str(runtime_task.get("session_id") or ""))
            runtime_task = dict(runtime_task)
            runtime_task["platform_user_id"] = str(session.get("platform_user_id") or "")
            runtime_task["platform"] = str(session.get("platform") or "")
            runtime_task["session_kind"] = str(session.get("kind") or "")
            item = _runtime_v2_task_to_item(runtime_task)
    if item is None:
        return await _build_task_list_payload(
            ctx,
            view=view,
            prefix="❌ 任务不存在或已删除。",
        )

    lines = [
        f"⚠️ 确认删除任务：`{item.task_id}`",
        "",
        f"- 状态：`{item.status}`",
        f"- 来源：`{item.source}`",
        f"- 目标：{str(item.goal or '').strip()}",
        "",
        "删除后这条任务会从任务列表中移除；如果它正处于会话活跃状态，也会一并清理。",
    ]
    confirm_token = _cache_task_action_ref(
        ctx,
        view=view,
        index=index,
        task_id=item.task_id,
    )

    return "\n".join(lines), {
        "actions": [
            [
                {
                    "text": "确认删除",
                    "callback_data": make_callback(
                        TASK_MENU_NS,
                        "deleteconfirm",
                        confirm_token,
                    ),
                },
                {
                    "text": "取消",
                    "callback_data": make_callback(TASK_MENU_NS, "show", view, index),
                },
            ],
            [
                {"text": "返回列表", "callback_data": make_callback(TASK_MENU_NS, view, 0)},
            ],
        ]
    }


async def _delete_task_from_menu(
    ctx: UnifiedContext,
    *,
    task_id: str,
) -> tuple[bool, str]:
    safe_task_id = str(task_id or "").strip()
    if not safe_task_id:
        return False, "❌ 缺少任务 ID。"

    user_id = get_effective_user_id(ctx)
    item = await task_inbox.get(safe_task_id)
    runtime_item = runtime_v2.get_task(safe_task_id)
    if item is None:
        if not runtime_item:
            return False, "❌ 任务不存在或已删除。"
        session = runtime_v2.get_session(str(runtime_item.get("session_id") or ""))
        if str(session.get("platform_user_id") or "").strip() != user_id:
            return False, "❌ 任务不存在或已删除。"
    elif str(item.user_id or "").strip() != user_id:
        return False, "❌ 任务不存在或已删除。"

    cleared_active = False
    try:
        active = channel_runtime_store.get_active_task(platform_user_id=user_id)
        if not active:
            active = await heartbeat_store.get_session_active_task(user_id)
        active_ids = {
            str((active or {}).get("id") or "").strip(),
            str((active or {}).get("task_inbox_id") or "").strip(),
            str((active or {}).get("session_task_id") or "").strip(),
        }
        active_ids.discard("")
        if safe_task_id in active_ids:
            channel_runtime_store.update_active_task(
                platform_user_id=user_id,
                status="cancelled",
                result_summary="Deleted from /task menu.",
                needs_confirmation=False,
                confirmation_deadline="",
                clear_active=True,
            )
            await heartbeat_store.update_session_active_task(
                user_id,
                status="cancelled",
                result_summary="Deleted from /task menu.",
                needs_confirmation=False,
                confirmation_deadline="",
                clear_active=True,
            )
            await heartbeat_store.append_session_event(
                user_id,
                f"user_deleted_task:{safe_task_id}",
            )
            cleared_active = True
    except Exception:
        logger.warning("failed to clear heartbeat active task for %s", safe_task_id, exc_info=True)

    cancelled_runtime = False
    try:
        from core.task_manager import task_manager

        active_info = task_manager.get_task_info(user_id) or {}
        tracked_ids = {
            str(active_info.get("active_task_id") or "").strip(),
            str(active_info.get("task_id") or "").strip(),
        }
        tracked_ids.discard("")
        if safe_task_id in tracked_ids:
            await task_manager.cancel_task(user_id)
            cancelled_runtime = True
            try:
                from core.subagent_supervisor import subagent_supervisor

                await subagent_supervisor.cancel_for_user(
                    user_id=user_id,
                    reason="deleted_from_task_menu",
                )
            except Exception:
                logger.warning("failed to cancel subagents for %s", safe_task_id, exc_info=True)
    except Exception:
        logger.warning("failed to cancel runtime task for %s", safe_task_id, exc_info=True)

    user_data = getattr(ctx, "user_data", None)
    if isinstance(user_data, dict) and str(user_data.get("task_inbox_id") or "").strip() == safe_task_id:
        user_data.pop("task_inbox_id", None)

    deleted = False
    if item is not None:
        deleted = await task_inbox.delete(safe_task_id)
    else:
        deleted = bool(
            runtime_v2.mark_task_deleted(
                safe_task_id,
                reason="Deleted from /task menu.",
            )
        )
    if not deleted:
        return False, "❌ 任务不存在或已删除。"

    suffix = ""
    if cleared_active or cancelled_runtime:
        suffix = " 已同步清理活跃任务状态。"
    return True, f"已删除任务 `{safe_task_id}`。{suffix}".strip()


async def task_command(ctx: UnifiedContext) -> None:
    if not await check_permission_unified(ctx):
        return

    text = getattr(ctx.message, "text", "") or ""
    sub, _args = _parse_subcommand(text)
    if sub not in {"recent", "list", "ls", "open", "diag"}:
        await ctx.reply(_task_usage_text())
        return

    if sub == "diag":
        await ctx.reply(await _build_task_diag_payload(ctx))
        return

    normalized_view = "open" if sub == "open" else "recent"
    payload, ui = await _build_task_list_payload(ctx, view=normalized_view)
    await ctx.reply(payload, ui=ui)


async def handle_task_callback(ctx: UnifiedContext) -> None:
    data = ctx.callback_data
    if not data:
        return

    action, parts = parse_callback(data, TASK_MENU_NS)
    if not action:
        return

    if action in {"recent", "open"}:
        page = int(str(parts[0] if parts else "0") or "0")
        payload, ui = await _build_task_list_payload(ctx, view=action, page=page)
    elif action == "show":
        view = str(parts[0] if parts else "recent").strip() or "recent"
        index = parts[1] if len(parts) >= 2 else ""
        payload, ui = await _build_task_detail_payload(ctx, view=view, index=index)
    elif action == "delete":
        if len(parts) == 1:
            view, index, task_id = _resolve_task_action_ref(ctx, parts[0])
        else:
            view = str(parts[0] if parts else "recent").strip() or "recent"
            index = parts[1] if len(parts) >= 2 else ""
            task_id = str(parts[2] if len(parts) >= 3 else "").strip()
        payload, ui = await _build_task_delete_confirm_payload(
            ctx,
            view=view or "recent",
            index=index,
            task_id=task_id,
        )
    elif action == "deleteconfirm":
        if len(parts) == 1:
            view, _index, task_id = _resolve_task_action_ref(ctx, parts[0])
        else:
            view = str(parts[0] if parts else "recent").strip() or "recent"
            task_id = str(parts[2] if len(parts) >= 3 else "").strip()
        ok, prefix = await _delete_task_from_menu(ctx, task_id=task_id)
        payload, ui = await _build_task_list_payload(
            ctx,
            view=view or "recent",
            prefix=prefix,
        )
    else:
        payload, ui = await _build_task_list_payload(
            ctx,
            view="recent",
            prefix="❌ 未识别的任务菜单操作。",
        )

    await edit_callback_message(ctx, payload, ui=ui)
