from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from core.task_inbox import task_inbox
from core.tools.dev_tools import dev_tools
from core.tools.dispatch_tools import dispatch_tools


SkillToolHandler = Callable[[Any, Dict[str, Any]], Awaitable[Dict[str, Any]]]


class SkillToolHandlerRegistry:
    def __init__(self) -> None:
        self._handlers: Dict[str, SkillToolHandler] = {}

    def register(self, handler_id: str, handler: SkillToolHandler) -> None:
        safe_handler_id = str(handler_id or "").strip()
        if not safe_handler_id:
            return
        self._handlers[safe_handler_id] = handler

    async def dispatch(
        self,
        handler_id: str,
        *,
        dispatcher: Any,
        args: Dict[str, Any],
    ) -> Dict[str, Any]:
        safe_handler_id = str(handler_id or "").strip()
        handler = self._handlers.get(safe_handler_id)
        if handler is None:
            return {
                "ok": False,
                "error_code": "unsupported_skill_tool_handler",
                "message": f"Unsupported skill tool handler: {safe_handler_id}",
                "failure_mode": "recoverable",
            }
        return await handler(dispatcher, dict(args or {}))


def _dispatch_metadata_from_runtime(
    dispatcher: Any,
    tool_args: Dict[str, Any],
) -> Dict[str, Any]:
    metadata = tool_args.get("metadata")
    metadata_obj = dict(metadata) if isinstance(metadata, dict) else {}
    ctx_user_data = getattr(dispatcher.ctx, "user_data", None)
    user_data = ctx_user_data if isinstance(ctx_user_data, dict) else {}
    msg = getattr(dispatcher.ctx, "message", None)
    msg_user = getattr(msg, "user", None)
    msg_chat = getattr(msg, "chat", None)
    if "user_id" not in metadata_obj:
        metadata_obj["user_id"] = str(getattr(msg_user, "id", "") or "")
    if "chat_id" not in metadata_obj:
        metadata_obj["chat_id"] = str(getattr(msg_chat, "id", "") or "")
    if "platform" not in metadata_obj:
        metadata_obj["platform"] = str(getattr(msg, "platform", "") or "")

    forced_platform = str(user_data.get("worker_delivery_platform") or "").strip()
    forced_chat_id = str(user_data.get("worker_delivery_chat_id") or "").strip()
    if forced_platform:
        metadata_obj["platform"] = forced_platform
    if forced_chat_id:
        metadata_obj["chat_id"] = forced_chat_id
    if "session_id" not in metadata_obj:
        metadata_obj["session_id"] = str(dispatcher.task_id or "")
    return metadata_obj


async def _list_workers_handler(
    dispatcher: Any,
    tool_args: Dict[str, Any],
) -> Dict[str, Any]:
    _ = (dispatcher, tool_args)
    return await dispatch_tools.list_workers()


async def _dispatch_worker_handler(
    dispatcher: Any,
    tool_args: Dict[str, Any],
) -> Dict[str, Any]:
    result = await dispatch_tools.dispatch_worker(
        instruction=str(tool_args.get("instruction") or ""),
        worker_id=str(tool_args.get("worker_id") or ""),
        backend=str(tool_args.get("backend") or ""),
        priority=tool_args.get("priority"),
        metadata=_dispatch_metadata_from_runtime(dispatcher, tool_args),
    )
    if dispatcher.task_inbox_id:
        dispatched_worker_id = str(result.get("worker_id") or "").strip()
        if dispatched_worker_id:
            try:
                await task_inbox.assign_worker(
                    dispatcher.task_inbox_id,
                    worker_id=dispatched_worker_id,
                    reason=str(result.get("selection_reason") or ""),
                    manager_id="core-manager",
                )
            except Exception:
                pass
    if dispatcher.on_worker_dispatched is not None:
        dispatcher.on_worker_dispatched(
            str(result.get("worker_id") or "").strip(),
            str(result.get("worker_name") or "").strip(),
        )
    return result


async def _worker_status_handler(
    dispatcher: Any,
    tool_args: Dict[str, Any],
) -> Dict[str, Any]:
    _ = dispatcher
    return await dispatch_tools.worker_status(
        worker_id=str(tool_args.get("worker_id") or ""),
        limit=int(tool_args.get("limit", 10) or 10),
    )


async def _software_delivery_handler(
    dispatcher: Any,
    tool_args: Dict[str, Any],
) -> Dict[str, Any]:
    user_request = dispatcher._extract_user_request()
    requested_action = dispatcher._infer_software_delivery_action(
        requested_action=str(tool_args.get("action") or "run"),
        user_request=user_request,
        args=dict(tool_args),
    )
    requested_requirement = str(tool_args.get("requirement") or "")
    requested_instruction = str(tool_args.get("instruction") or "")
    return await dev_tools.software_delivery(
        action=requested_action,
        task_id=str(tool_args.get("task_id") or ""),
        requirement=requested_requirement or user_request,
        instruction=requested_instruction or requested_requirement or user_request,
        issue=str(tool_args.get("issue") or ""),
        repo_path=str(tool_args.get("repo_path") or ""),
        repo_url=str(tool_args.get("repo_url") or ""),
        cwd=str(tool_args.get("cwd") or ""),
        skill_name=str(tool_args.get("skill_name") or ""),
        source=str(tool_args.get("source") or ""),
        template_kind=str(tool_args.get("template_kind") or ""),
        owner=str(tool_args.get("owner") or ""),
        repo=str(tool_args.get("repo") or ""),
        backend=str(tool_args.get("backend") or ""),
        branch_name=str(tool_args.get("branch_name") or ""),
        base_branch=str(tool_args.get("base_branch") or ""),
        commit_message=str(tool_args.get("commit_message") or ""),
        pr_title=str(tool_args.get("pr_title") or ""),
        pr_body=str(tool_args.get("pr_body") or ""),
        timeout_sec=tool_args.get("timeout_sec", 1800),
        validation_commands=tool_args.get("validation_commands"),
        auto_publish=tool_args.get("auto_publish", True),
        auto_push=tool_args.get("auto_push", True),
        auto_pr=tool_args.get("auto_pr", True),
        target_service=str(tool_args.get("target_service") or ""),
        rollout=str(tool_args.get("rollout") or ""),
        validate_only=tool_args.get("validate_only", False),
    )


skill_tool_handler_registry = SkillToolHandlerRegistry()
skill_tool_handler_registry.register(
    "manager.worker_management.list",
    _list_workers_handler,
)
skill_tool_handler_registry.register(
    "manager.worker_management.dispatch",
    _dispatch_worker_handler,
)
skill_tool_handler_registry.register(
    "manager.worker_management.status",
    _worker_status_handler,
)
skill_tool_handler_registry.register(
    "manager.software_delivery",
    _software_delivery_handler,
)
