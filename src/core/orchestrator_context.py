from __future__ import annotations

import datetime
import contextlib
import logging
from dataclasses import dataclass
from typing import Any, Dict

from core.channel_runtime_store import channel_runtime_store
from core.heartbeat_store import heartbeat_store
from core.runtime_v2 import TERMINAL_STATUSES, runtime_v2
from core.task_inbox import task_inbox
from core.task_manager import task_manager
from core.tool_access_store import tool_access_store

logger = logging.getLogger(__name__)


@dataclass
class OrchestratorRuntimeContext:
    user_id: str
    user_data: Dict[str, Any]
    runtime_user_id: str
    platform_name: str
    subagent_runtime_user: bool
    heartbeat_runtime_user: bool
    session_state_enabled: bool
    runtime_policy_ctx: Dict[str, Any]
    runtime_agent_kind: str
    ikaros_runtime: bool
    task_id: str
    task_inbox_id: str
    session_id: str = ""
    runtime_v2_task_id: str = ""
    session_state_active: bool = False
    workspace_event_logged: bool = False

    @classmethod
    def from_message(cls, ctx: Any) -> "OrchestratorRuntimeContext":
        msg = getattr(ctx, "message", None)
        msg_user = getattr(msg, "user", None)
        user_id = str(getattr(msg_user, "id", "") or "")
        user_data = getattr(ctx, "user_data", None)
        if not isinstance(user_data, dict):
            user_data = {}
            with contextlib.suppress(Exception):
                setattr(ctx, "user_data", user_data)

        runtime_user_id = str(user_data.get("runtime_user_id") or "").strip() or user_id
        platform_name = str(getattr(msg, "platform", "") or "").strip().lower()
        subagent_runtime_user = (
            platform_name == "subagent_kernel"
            or runtime_user_id.startswith("subagent::")
            or str(user_data.get("runtime_agent_kind") or "").strip().lower()
            == "subagent"
        )
        heartbeat_runtime_user = platform_name == "heartbeat_daemon"
        heartbeat_session_state_enabled = bool(
            user_data.get("heartbeat_session_state_enabled")
        )
        subagent_session_state_enabled = bool(
            user_data.get("subagent_session_state_enabled")
        )
        session_state_enabled = not subagent_runtime_user and (
            not heartbeat_runtime_user or heartbeat_session_state_enabled
        )
        if subagent_runtime_user and subagent_session_state_enabled:
            session_state_enabled = True

        runtime_policy_ctx = tool_access_store.resolve_runtime_policy(
            runtime_user_id=runtime_user_id,
            platform=platform_name,
        )
        runtime_agent_kind = (
            str(runtime_policy_ctx.get("agent_kind") or "").strip().lower()
        )
        ikaros_runtime = runtime_agent_kind == "core-ikaros"

        task_info = task_manager.get_task_info(user_id)
        runtime_task_id = str(user_data.get("runtime_task_id") or "").strip()
        task_id = runtime_task_id
        if not task_id and isinstance(task_info, dict):
            task_id = str(task_info.get("task_id") or "").strip()
        if not task_id:
            task_id = f"{int(datetime.datetime.now().timestamp())}"
        task_inbox_id = str(user_data.get("task_inbox_id") or "").strip()
        session_id = str(user_data.get("current_session_id") or "").strip()

        return cls(
            user_id=user_id,
            user_data=user_data,
            runtime_user_id=runtime_user_id,
            platform_name=platform_name,
            subagent_runtime_user=subagent_runtime_user,
            heartbeat_runtime_user=heartbeat_runtime_user,
            session_state_enabled=session_state_enabled,
            runtime_policy_ctx=runtime_policy_ctx,
            runtime_agent_kind=runtime_agent_kind,
            ikaros_runtime=ikaros_runtime,
            task_id=str(task_id),
            task_inbox_id=task_inbox_id,
            session_id=session_id,
        )

    async def append_session_event(self, note: str) -> None:
        if not self.session_state_enabled:
            return
        await heartbeat_store.append_session_event(self.user_id, note)

    def _task_inbox_source(self) -> str:
        if self.heartbeat_runtime_user:
            return "heartbeat"
        if self.subagent_runtime_user:
            return "subagent"
        return "user_chat"

    def _runtime_v2_session_id(self) -> str:
        existing = str(self.user_data.get("runtime_v2_session_id") or "").strip()
        if existing:
            return existing
        if self.session_id:
            return self.session_id
        platform = self.platform_name or "channel"
        user_id = self.user_id or self.runtime_user_id or "user"
        return f"{platform}:{user_id}:main"

    def _runtime_v2_session_kind(self, session_id: str) -> str:
        if self.platform_name == "scheduler" or session_id.startswith("scheduler-task-"):
            return "scheduled_task"
        if self.platform_name == "web":
            return "web_workspace"
        return "channel_chat"

    def _runtime_v2_turn_source(self) -> str:
        if self.platform_name == "scheduler":
            return "scheduler"
        if self.heartbeat_runtime_user:
            return "system"
        return "user"

    def _usable_runtime_v2_task_id(
        self,
        task_id: str,
        *,
        session_id: str,
        goal: str,
    ) -> str:
        safe_task_id = str(task_id or "").strip()
        if not safe_task_id:
            return ""
        task = runtime_v2.get_task(safe_task_id)
        if not task:
            return ""
        if str(task.get("status") or "").strip() in TERMINAL_STATUSES:
            return ""
        if session_id and str(task.get("session_id") or "").strip() != session_id:
            return ""
        existing_goal = str(task.get("goal") or "").strip()
        if goal and existing_goal and existing_goal != goal:
            return ""
        return safe_task_id

    async def ensure_task_inbox(self, *, task_goal: str) -> str:
        if self.task_inbox_id:
            self.user_data["task_inbox_id"] = self.task_inbox_id
            return self.task_inbox_id
        if not self.session_state_enabled:
            return ""

        goal = str(task_goal or "").strip()
        if not goal or not self.user_id:
            return ""

        try:
            payload = {
                "task_id": self.task_id,
                "runtime_user_id": self.runtime_user_id,
                "platform": self.platform_name,
            }
            metadata = {
                "runtime_agent_kind": self.runtime_agent_kind,
            }
            if self.session_id:
                payload["session_id"] = self.session_id
                metadata["session_id"] = self.session_id
            envelope = await task_inbox.submit(
                source=self._task_inbox_source(),
                goal=goal,
                user_id=self.user_id,
                payload=payload,
                priority="normal",
                requires_reply=bool(self.ikaros_runtime),
                metadata=metadata,
            )
        except Exception as exc:
            logger.warning(
                "Failed to create task inbox entry for user=%s: %s",
                self.user_id,
                exc,
            )
            return ""

        self.task_inbox_id = str(getattr(envelope, "task_id", "") or "").strip()
        if self.task_inbox_id:
            self.user_data["task_inbox_id"] = self.task_inbox_id
        return self.task_inbox_id

    async def ensure_runtime_v2_task(self, *, task_goal: str) -> str:
        if not self.session_state_enabled:
            return ""

        goal = str(task_goal or "").strip()
        if not goal:
            return ""

        session_id = self._runtime_v2_session_id()
        if not session_id:
            return ""
        existing = str(
            self.runtime_v2_task_id or self.user_data.get("runtime_v2_task_id") or ""
        ).strip()
        usable_existing = self._usable_runtime_v2_task_id(
            existing,
            session_id=session_id,
            goal=goal,
        )
        if usable_existing:
            self.runtime_v2_task_id = usable_existing
            self.user_data["runtime_v2_task_id"] = usable_existing
            return usable_existing
        if existing:
            self.runtime_v2_task_id = ""
            self.user_data.pop("runtime_v2_task_id", None)
        session = runtime_v2.ensure_session(
            session_id=session_id,
            kind=self._runtime_v2_session_kind(session_id),
            platform=self.platform_name,
            platform_user_id=self.user_id or self.runtime_user_id,
            title=goal[:80],
            metadata={
                "runtime_task_id": self.task_id,
                "task_inbox_id": self.task_inbox_id,
            },
        )
        runtime_turn_id = str(self.user_data.get("runtime_v2_turn_id") or "").strip()
        current_turn = runtime_v2.get_turn(runtime_turn_id) if runtime_turn_id else {}
        current_turn_status = str(current_turn.get("status") or "").strip()
        if (
            not current_turn
            or str(current_turn.get("session_id") or "").strip() != session["id"]
            or current_turn_status in TERMINAL_STATUSES
        ):
            runtime_turn_id = ""
        if runtime_turn_id and current_turn_status == "queued":
            runtime_v2.update_turn_status(runtime_turn_id, "running")
        if not runtime_turn_id:
            turn = runtime_v2.create_turn(
                session_id=session["id"],
                source=self._runtime_v2_turn_source(),
                input_text=goal,
                status="running",
                metadata={
                    "runtime_task_id": self.task_id,
                    "task_inbox_id": self.task_inbox_id,
                    "platform": self.platform_name,
                },
            )
            runtime_turn_id = str(turn.get("id") or "").strip()

        task = runtime_v2.create_task(
            session_id=session["id"],
            turn_id=runtime_turn_id,
            goal=goal,
            status="running",
            metadata={
                "runtime_task_id": self.task_id,
                "task_inbox_id": self.task_inbox_id,
                "source": self._task_inbox_source(),
            },
        )
        self.runtime_v2_task_id = str(task.get("id") or "").strip()
        if self.runtime_v2_task_id:
            self.user_data["runtime_v2_session_id"] = session["id"]
            self.user_data["runtime_v2_turn_id"] = runtime_turn_id
            self.user_data["runtime_v2_task_id"] = self.runtime_v2_task_id
        return self.runtime_v2_task_id

    async def update_session_task(
        self,
        *,
        status: str | None = None,
        result_summary: str | None = None,
        clear_active: bool = False,
        needs_confirmation: bool | None = None,
        confirmation_deadline: str | None = None,
    ) -> None:
        if not self.session_state_enabled:
            return
        fields: Dict[str, Any] = {}
        if status is not None:
            fields["status"] = status
        if result_summary is not None:
            fields["result_summary"] = result_summary[:500]
        if needs_confirmation is not None:
            fields["needs_confirmation"] = bool(needs_confirmation)
        if confirmation_deadline is not None:
            fields["confirmation_deadline"] = confirmation_deadline
        if clear_active:
            fields["clear_active"] = True
        if fields:
            if not self.heartbeat_runtime_user and not self.subagent_runtime_user:
                channel_runtime_store.update_active_task(
                    platform=self.platform_name,
                    platform_user_id=self.user_id,
                    **fields,
                )
                await heartbeat_store.update_session_active_task(self.user_id, **fields)
            else:
                await heartbeat_store.update_session_active_task(self.user_id, **fields)

    async def update_task_inbox_status(
        self,
        *,
        status: str,
        event: str,
        detail: str = "",
        **fields: Any,
    ) -> None:
        if not self.task_inbox_id:
            return
        await task_inbox.update_status(
            self.task_inbox_id,
            status,
            event=event,
            detail=detail,
            **fields,
        )

    async def mark_ikaros_loop_started(self, task_goal: str) -> None:
        if not self.task_inbox_id:
            return
        await self.update_task_inbox_status(
            status="running",
            event="ikaros_loop_started",
            detail=(task_goal or "")[:180],
            ikaros_id="core-ikaros",
        )

    async def activate_session(
        self, *, task_goal: str, task_workspace_root: str
    ) -> None:
        if not self.session_state_enabled:
            return
        payload = {
            "id": self.task_id,
            "session_task_id": self.task_inbox_id or self.task_id,
            "task_inbox_id": self.task_inbox_id,
            "goal": task_goal,
            "status": "running",
            "source": self._task_inbox_source(),
            "result_summary": "",
            "needs_confirmation": False,
            "confirmation_deadline": "",
            "stage_index": 0,
            "stage_total": 0,
            "stage_id": "",
            "stage_title": "",
            "attempt_index": 0,
            "last_blocking_reason": "",
            "resume_instruction_preview": "",
            "adjustments_count": 0,
            "kernel_provider": "",
            "kernel_status": "",
        }
        if not self.heartbeat_runtime_user and not self.subagent_runtime_user:
            channel_runtime_store.set_active_task(
                payload,
                platform=self.platform_name,
                platform_user_id=self.user_id,
            )
            await heartbeat_store.set_session_active_task(
                self.user_id,
                payload,
            )
        else:
            await heartbeat_store.set_session_active_task(
                self.user_id,
                payload,
            )
        task_manager.set_heartbeat_path(
            self.user_id, str(heartbeat_store.heartbeat_path(self.user_id))
        )
        task_manager.set_active_task_id(self.user_id, self.task_id)
        task_manager.heartbeat(self.user_id, f"session:{self.task_id}:running")
        await self.append_session_event(f"session_started:{self.task_id}")
        self.session_state_active = True
        if task_workspace_root and not self.workspace_event_logged:
            await self.append_session_event(f"workspace_root:{task_workspace_root}")
            self.workspace_event_logged = True
