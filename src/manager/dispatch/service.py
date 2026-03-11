from __future__ import annotations

from dataclasses import dataclass, field
import logging
import os
from typing import Any, Dict, List

from core.heartbeat_store import heartbeat_store
from core.task_inbox import task_inbox
from manager.planning.stage_planner import (
    build_stage_instruction,
    count_adjustments,
    get_current_stage,
    get_stage_position,
    mark_stage_running,
    normalize_stage_plan,
)
from core.worker_store import worker_registry, worker_task_store
from shared.queue.dispatch_queue import dispatch_queue

logger = logging.getLogger(__name__)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return int(default)


def _dispatch_priority(*, source: str, metadata: Dict[str, Any]) -> int:
    if "priority" in metadata:
        return max(-100, min(100, _safe_int(metadata.get("priority"), 0)))
    normalized_source = str(source or "").strip().lower()
    if normalized_source == "user_cmd":
        return 80
    if normalized_source == "user_chat":
        return 60
    if normalized_source == "heartbeat":
        return 20
    if normalized_source == "system":
        return 10
    return 40


def _safe_text(value: Any, *, limit: int = 4000) -> str:
    return str(value or "").strip()[:limit]


def _session_task_id_from_metadata(metadata: Dict[str, Any]) -> str:
    return (
        _safe_text(metadata.get("session_task_id"), limit=80)
        or _safe_text(metadata.get("task_inbox_id"), limit=80)
        or _safe_text(metadata.get("session_id"), limit=80)
    )


def _is_staged_session(metadata: Dict[str, Any]) -> bool:
    if str(metadata.get("staged_session") or "").strip().lower() == "true":
        return True
    return bool(_session_task_id_from_metadata(metadata))


def _prepare_stage_dispatch(
    *,
    instruction: str,
    metadata: Dict[str, Any],
) -> tuple[str, Dict[str, Any]]:
    meta = dict(metadata or {})
    if not _is_staged_session(meta):
        return instruction, meta

    resolved_task_goal = (
        _safe_text(meta.get("task_goal"), limit=6000)
        or _safe_text(instruction, limit=6000)
        or _safe_text(meta.get("original_user_request"), limit=6000)
    )
    original_request = (
        _safe_text(meta.get("original_user_request"), limit=6000)
        or resolved_task_goal
    )
    session_task_id = _session_task_id_from_metadata(meta)
    stage_plan = normalize_stage_plan(
        meta.get("stage_plan") if isinstance(meta.get("stage_plan"), dict) else None,
        original_request=resolved_task_goal,
    )
    current_stage = get_current_stage(stage_plan)
    if current_stage is None:
        return instruction, meta

    stage_id = _safe_text(current_stage.get("id"), limit=80)
    stage_plan = mark_stage_running(stage_plan, stage_id=stage_id)
    current_stage = get_current_stage(stage_plan) or current_stage
    stage_index, stage_total = get_stage_position(stage_plan, stage_id)
    attempt_index = max(1, int(current_stage.get("attempt_count") or 1))
    prepared_instruction = build_stage_instruction(
        original_request=resolved_task_goal,
        plan=stage_plan,
        stage=current_stage,
        previous_summary=_safe_text(stage_plan.get("last_stage_summary"), limit=1200),
        previous_output=_safe_text(stage_plan.get("last_stage_output"), limit=2400),
        last_blocking_reason=_safe_text(meta.get("last_blocking_reason"), limit=1200),
    )

    meta["staged_session"] = True
    meta["session_task_id"] = session_task_id
    meta["task_goal"] = resolved_task_goal
    meta["original_user_request"] = original_request
    meta["stage_plan"] = stage_plan
    meta["stage_id"] = stage_id
    meta["stage_title"] = _safe_text(current_stage.get("title"), limit=200)
    meta["stage_index"] = stage_index
    meta["stage_total"] = stage_total
    meta["attempt_index"] = attempt_index
    meta["resume_instruction_preview"] = _safe_text(prepared_instruction, limit=1200)
    meta["adjustments_count"] = count_adjustments(stage_plan)
    meta["user_visible_task_id"] = session_task_id
    return prepared_instruction, meta


def _score_worker(
    goal: str,
    worker: Dict[str, Any],
    *,
    metrics: Dict[str, Any],
    recent_error_rate: float,
) -> int:
    text = str(goal or "").lower()
    score = 0
    status = str(worker.get("status") or "").lower()
    if status == "ready":
        score += 100
    elif status == "busy":
        score -= 40

    capabilities = [str(item).lower() for item in (worker.get("capabilities") or [])]
    summary = str(worker.get("summary") or "").lower()
    merged_cap = " ".join(capabilities + [summary])

    if any(token in text for token in ("rss", "订阅", "feed")) and (
        "rss" in merged_cap or "feed" in merged_cap
    ):
        score += 40
    if any(token in text for token in ("股票", "stock", "quote")) and (
        "stock" in merged_cap
    ):
        score += 40
    if any(token in text for token in ("部署", "deploy", "docker")) and any(
        token in merged_cap for token in ("deploy", "docker", "ops")
    ):
        score += 40

    running = max(0, _safe_int(metrics.get("running"), 0))
    pending = max(0, _safe_int(metrics.get("pending"), 0))
    queue_depth = max(0, _safe_int(metrics.get("queue_depth"), pending + running))
    score -= running * 25
    score -= pending * 12
    score -= queue_depth * 4
    score -= int(max(0.0, float(recent_error_rate or 0.0)) * 80)
    return score


@dataclass
class WorkerSelection:
    worker_id: str
    reason: str
    auto_selected: bool = False
    score: int = 0
    metrics: Dict[str, Any] = field(default_factory=dict)


class ManagerDispatchService:
    async def _sync_session_dispatch_state(
        self,
        *,
        metadata: Dict[str, Any],
        worker_name: str,
        worker_id: str,
    ) -> None:
        user_id = _safe_text(metadata.get("user_id"), limit=80)
        task_inbox_id = _safe_text(metadata.get("task_inbox_id"), limit=80)
        session_task_id = _session_task_id_from_metadata(metadata)
        stage_index = max(0, int(metadata.get("stage_index") or 0))
        stage_total = max(0, int(metadata.get("stage_total") or 0))
        stage_id = _safe_text(metadata.get("stage_id"), limit=80)
        stage_title = _safe_text(metadata.get("stage_title"), limit=200)
        attempt_index = max(0, int(metadata.get("attempt_index") or 0))
        adjustments_count = max(0, int(metadata.get("adjustments_count") or 0))
        resume_preview = _safe_text(metadata.get("resume_instruction_preview"), limit=2000)
        task_goal = _safe_text(metadata.get("task_goal"), limit=2000)

        if task_inbox_id:
            try:
                task_obj = await task_inbox.get(task_inbox_id)
                merged_metadata = dict((task_obj.metadata if task_obj else {}) or {})
                merged_metadata.update(
                    {
                        "stage_plan": dict(metadata.get("stage_plan") or {}),
                        "session_task_id": session_task_id,
                        "stage_id": stage_id,
                        "stage_index": stage_index,
                        "stage_total": stage_total,
                        "attempt_index": attempt_index,
                        "task_goal": _safe_text(metadata.get("task_goal"), limit=6000),
                        "original_user_request": _safe_text(
                            metadata.get("original_user_request"), limit=6000
                        ),
                    }
                )
                await task_inbox.update_status(
                    task_inbox_id,
                    "running",
                    event="stage_attempt_dispatched",
                    detail=(
                        f"worker={worker_name or worker_id}; "
                        f"stage={stage_index}/{max(1, stage_total)}:{stage_title or stage_id}"
                    )[:200],
                    metadata=merged_metadata,
                )
            except Exception:
                logger.debug(
                    "Failed to sync staged task inbox state task=%s",
                    task_inbox_id,
                    exc_info=True,
                )

        if user_id:
            try:
                await heartbeat_store.update_session_active_task(
                    user_id,
                    session_task_id=session_task_id,
                    task_inbox_id=task_inbox_id,
                    status="running",
                    goal=task_goal,
                    stage_index=stage_index,
                    stage_total=stage_total,
                    stage_id=stage_id,
                    stage_title=stage_title,
                    attempt_index=attempt_index,
                    result_summary=(
                        f"正在推进阶段 {stage_index}/{max(1, stage_total)}："
                        f"{stage_title or stage_id or '执行任务'}"
                    )[:500],
                    needs_confirmation=False,
                    confirmation_deadline="",
                    last_blocking_reason="",
                    resume_instruction_preview=resume_preview,
                    adjustments_count=adjustments_count,
                )
            except Exception:
                logger.debug(
                    "Failed to sync staged active task user=%s",
                    user_id,
                    exc_info=True,
                )

    async def _recent_error_rate(self, worker_id: str, *, limit: int = 12) -> float:
        rows = await worker_task_store.list_recent(worker_id=worker_id, limit=limit)
        if not rows:
            return 0.0
        failures = 0
        checked = 0
        for row in rows:
            status = str(row.get("status") or "").strip().lower()
            if status not in {"done", "failed", "cancelled"}:
                continue
            checked += 1
            if status in {"failed", "cancelled"}:
                failures += 1
        if checked <= 0:
            return 0.0
        return round(failures / checked, 3)

    async def _worker_metrics_snapshot(self, worker_id: str) -> Dict[str, Any]:
        metrics = await dispatch_queue.worker_metrics(worker_id=worker_id, limit=50)
        metrics["recent_error_rate"] = await self._recent_error_rate(worker_id)
        return metrics

    async def list_workers(self) -> Dict[str, Any]:
        workers = await worker_registry.list_workers()
        rows: List[Dict[str, Any]] = []
        for item in workers:
            worker_id = str(item.get("id") or "")
            metrics = await self._worker_metrics_snapshot(worker_id)
            rows.append(
                {
                    "id": worker_id,
                    "name": str(item.get("name") or ""),
                    "status": str(item.get("status") or "unknown"),
                    "backend": str(item.get("backend") or ""),
                    "capabilities": list(item.get("capabilities") or []),
                    "summary": str(item.get("summary") or ""),
                    "last_task_id": str(item.get("last_task_id") or ""),
                    "last_error": str(item.get("last_error") or ""),
                    "load": {
                        "queue_depth": int(metrics.get("queue_depth") or 0),
                        "pending": int(metrics.get("pending") or 0),
                        "running": int(metrics.get("running") or 0),
                    },
                    "recent_error_rate": float(metrics.get("recent_error_rate") or 0.0),
                    "avg_dispatch_latency_sec": float(
                        metrics.get("avg_dispatch_latency_sec") or 0.0
                    ),
                    "avg_completion_sec": float(
                        metrics.get("avg_completion_sec") or 0.0
                    ),
                }
            )
        return {
            "ok": True,
            "workers": rows,
            "summary": f"{len(rows)} worker(s) available",
        }

    async def _choose_worker(
        self,
        *,
        goal: str,
        preferred_worker_id: str = "",
    ) -> WorkerSelection:
        preferred = str(preferred_worker_id or "").strip().lower()
        if preferred:
            worker = await worker_registry.get_worker(preferred)
            if worker:
                status = str(worker.get("status") or "").lower()
                metrics = await self._worker_metrics_snapshot(str(worker.get("id") or preferred))
                reason = (
                    "preferred_worker" if status == "ready" else "preferred_worker_busy"
                )
                return WorkerSelection(
                    worker_id=str(worker.get("id") or preferred),
                    reason=reason,
                    score=999 if status == "ready" else 500,
                    metrics=metrics,
                )

        workers = await worker_registry.list_workers()
        if not workers:
            worker = await worker_registry.ensure_default_worker()
            metrics = await self._worker_metrics_snapshot(str(worker.get("id") or "worker-main"))
            return WorkerSelection(
                worker_id=str(worker.get("id") or "worker-main"),
                reason="created_default_worker",
                auto_selected=True,
                score=0,
                metrics=metrics,
            )

        ranked: List[tuple[int, Dict[str, Any], Dict[str, Any]]] = []
        for item in workers:
            worker_id = str(item.get("id") or "").strip()
            metrics = await self._worker_metrics_snapshot(worker_id)
            recent_error_rate = float(metrics.get("recent_error_rate") or 0.0)
            score = _score_worker(
                goal,
                item,
                metrics=metrics,
                recent_error_rate=recent_error_rate,
            )
            ranked.append((score, item, metrics))
        ranked.sort(key=lambda item: item[0], reverse=True)
        picked_score, picked, picked_metrics = ranked[0]
        return WorkerSelection(
            worker_id=str(picked.get("id") or "worker-main"),
            reason="llm_unspecified_auto_pick",
            auto_selected=True,
            score=int(picked_score),
            metrics=picked_metrics,
        )

    async def dispatch_worker(
        self,
        *,
        instruction: str,
        worker_id: str = "",
        backend: str = "",
        priority: Any = None,
        source: str = "manager_dispatch",
        metadata: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        task_instruction = str(instruction or "").strip()
        if not task_instruction:
            return {
                "ok": False,
                "error_code": "invalid_args",
                "message": "instruction is required",
            }

        meta = dict(metadata or {})
        task_instruction, meta = _prepare_stage_dispatch(
            instruction=task_instruction,
            metadata=meta,
        )
        if not str(meta.get("program_id") or "").strip():
            meta["program_id"] = (
                str(os.getenv("WORKER_DEFAULT_PROGRAM_ID", "default-worker")).strip()
                or "default-worker"
            )
        if not str(meta.get("program_version") or "").strip():
            meta["program_version"] = (
                str(os.getenv("WORKER_DEFAULT_PROGRAM_VERSION", "v1")).strip() or "v1"
            )
        has_explicit_priority = False
        try:
            explicit_priority = int(priority) if priority not in {None, ""} else 0
            has_explicit_priority = bool(explicit_priority) or "priority" in meta
        except Exception:
            explicit_priority = 0
        resolved_priority = (
            explicit_priority
            if has_explicit_priority
            else _dispatch_priority(source=source, metadata=meta)
        )
        priority = max(-100, min(100, int(resolved_priority)))
        meta["priority"] = priority
        selected = await self._choose_worker(
            goal=task_instruction,
            preferred_worker_id=worker_id,
        )
        selected_worker_id = selected.worker_id
        selected_worker = await worker_registry.get_worker(selected_worker_id)
        selected_worker_obj = dict(selected_worker or {})
        selected_worker_name = (
            str(selected_worker_obj.get("name") or selected_worker_id).strip()
            or selected_worker_id
        )
        meta.setdefault("worker_name", selected_worker_name)
        meta.setdefault("dispatch_component", "manager_dispatch_service")
        meta.setdefault("selection_reason", selected.reason)
        meta.setdefault("selection_score", int(selected.score or 0))
        meta.setdefault("worker_metrics", dict(selected.metrics or {}))
        meta.setdefault(
            "session_task_id",
            _session_task_id_from_metadata(meta) or str(meta.get("task_inbox_id") or ""),
        )
        meta.setdefault("user_visible_task_id", str(meta.get("session_task_id") or ""))

        queued = await dispatch_queue.submit_task(
            worker_id=selected_worker_id,
            instruction=task_instruction,
            source=str(source or "manager_dispatch"),
            backend=str(backend or ""),
            priority=priority,
            metadata=meta,
        )
        try:
            await worker_task_store.upsert_task(
                task_id=queued.task_id,
                worker_id=selected_worker_id,
                source=str(source or "manager_dispatch"),
                instruction=task_instruction,
                status="queued",
                metadata=meta,
                retry_count=int(getattr(queued, "retry_count", 0) or 0),
                created_at=str(getattr(queued, "created_at", "") or ""),
                result_summary="queued by manager dispatch",
            )
        except Exception as exc:
            logger.warning(
                "Failed to mirror queued task into WorkerTaskStore task_id=%s err=%s",
                str(getattr(queued, "task_id", "") or ""),
                exc,
            )

        if _is_staged_session(meta):
            await self._sync_session_dispatch_state(
                metadata=meta,
                worker_name=selected_worker_name,
                worker_id=selected_worker_id,
            )

        user_visible_task_id = (
            _safe_text(meta.get("user_visible_task_id"), limit=80)
            or queued.task_id
        )
        stage_index = max(0, int(meta.get("stage_index") or 0))
        stage_total = max(0, int(meta.get("stage_total") or 0))
        stage_hint = ""
        if stage_index > 0 and stage_total > 0:
            stage_hint = f"stage={stage_index}/{stage_total}; "
        manager_hint = (
            "worker dispatch accepted; "
            f"worker_name={selected_worker_name}; "
            f"task_id={user_visible_task_id}; "
            f"{stage_hint}"
            "status=running_async; "
            "reply user naturally in Chinese and mention the task id once."
        )
        return {
            "ok": True,
            "worker_id": selected_worker_id,
            "worker_name": selected_worker_name,
            "task_id": queued.task_id,
            "session_task_id": str(meta.get("session_task_id") or ""),
            "backend": str(backend or selected_worker_obj.get("backend") or ""),
            "result": "",
            "summary": f"worker job queued: {user_visible_task_id}"[:200],
            "text": manager_hint,
            "ui": {},
            "payload": {
                "text": manager_hint,
                "dispatch": "queued",
                "worker_name": selected_worker_name,
                "task_id": user_visible_task_id,
                "attempt_task_id": queued.task_id,
                "session_task_id": str(meta.get("session_task_id") or ""),
                "stage_index": stage_index,
                "stage_total": stage_total,
                "manager_reply_style": "natural",
                "priority": priority,
            },
            "error": "",
            "auto_selected": bool(selected.auto_selected),
            "selection_reason": selected.reason,
            "selection_score": int(selected.score or 0),
            "worker_metrics": dict(selected.metrics or {}),
            "priority": priority,
            "runtime_mode": "async_queue",
            "terminal": False,
            "task_outcome": "partial",
            "async_dispatch": True,
        }


manager_dispatch_service = ManagerDispatchService()
