from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import hashlib
import inspect
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List


MAX_OUTPUT_CHARS = 12000
MAX_LOG_CHARS = 1_000_000
MEDIA_EXTENSIONS = {
    ".png": "photo",
    ".jpg": "photo",
    ".jpeg": "photo",
    ".gif": "photo",
    ".webp": "photo",
    ".bmp": "photo",
    ".mp4": "video",
    ".mov": "video",
    ".webm": "video",
    ".mkv": "video",
    ".avi": "video",
    ".m4v": "video",
    ".mp3": "audio",
    ".wav": "audio",
    ".m4a": "audio",
    ".aac": "audio",
    ".ogg": "audio",
    ".flac": "audio",
}
DOCUMENT_EXTENSIONS = {
    ".pdf",
    ".txt",
    ".md",
    ".csv",
    ".tsv",
    ".json",
    ".jsonl",
    ".xlsx",
    ".xls",
    ".docx",
    ".pptx",
    ".zip",
}
PATH_KEYS = {
    "path",
    "file_path",
    "filepath",
    "filePath",
    "local_path",
    "localPath",
    "absolute_path",
    "absolutePath",
    "saved_path",
    "savedPath",
}


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _tail(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    payload = str(text or "")
    if len(payload) <= limit:
        return payload
    return payload[-limit:]


def _tail_for_log(text: str, limit: int = MAX_LOG_CHARS) -> str:
    payload = str(text or "")
    if len(payload) <= limit:
        return payload
    return payload[-limit:]


def _command_to_text(command: List[str]) -> str:
    return " ".join([json.dumps(str(part)) for part in list(command or []) if part])


def _append_app_server_log(
    *,
    log_path: str,
    command: List[str],
    cwd: str,
    thread_id: str,
    turn_id: str,
    status: str,
    stdout: str,
    stderr: str,
    timed_out: bool,
) -> None:
    safe_log_path = str(log_path or "").strip()
    if not safe_log_path:
        return
    try:
        target = Path(safe_log_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            f"[{_now_iso()}] transport=app-server command={_command_to_text(command)} cwd={cwd}",
            (
                f"thread_id={thread_id} turn_id={turn_id} "
                f"timed_out={str(bool(timed_out)).lower()} status={status}"
            ),
            "--- stdout ---",
            _tail_for_log(stdout),
            "--- stderr ---",
            _tail_for_log(stderr),
            "--- end ---",
            "",
        ]
        with target.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines))
    except Exception:
        return


class JsonRpcError(RuntimeError):
    def __init__(self, *, code: int, message: str, data: Any = None) -> None:
        super().__init__(str(message or "json-rpc error"))
        self.code = int(code)
        self.message = str(message or "json-rpc error")
        self.data = data


class CodexAppServerClient:
    def __init__(
        self,
        *,
        command: List[str],
        cwd: str,
        env: Dict[str, str],
        timeout_sec: int,
        request_timeout_sec: int = 45,
        log_path: str = "",
        model: str = "",
        effort: str = "",
        approval_policy: str = "never",
        sandbox: str = "workspace-write",
        approval_decision: str = "accept",
    ) -> None:
        self.command = [str(item) for item in list(command or []) if str(item)]
        self.cwd = str(cwd or "").strip()
        self.env = dict(env or {})
        self.timeout_sec = max(30, int(timeout_sec or 0))
        self.request_timeout_sec = max(5, int(request_timeout_sec or 0))
        self.log_path = str(log_path or "").strip()
        self.model = str(model or "").strip()
        self.effort = str(effort or "").strip()
        self.approval_policy = str(approval_policy or "never").strip() or "never"
        self.sandbox = str(sandbox or "workspace-write").strip() or "workspace-write"
        self.approval_decision = (
            str(approval_decision or "accept").strip() or "accept"
        )
        self.proc: asyncio.subprocess.Process | None = None
        self._request_lock = asyncio.Lock()
        self.event_callback: (
            Callable[[str, Dict[str, Any]], Awaitable[None] | None] | None
        ) = None
        self._reader_task: asyncio.Task[Any] | None = None
        self._stderr_task: asyncio.Task[Any] | None = None
        self._request_id = 0
        self._pending: Dict[int, asyncio.Future[Any]] = {}
        self._turn_waiters: Dict[str, asyncio.Future[Any]] = {}
        self.stderr_text = ""
        self.initialize_response: Dict[str, Any] = {}
        self.thread_response: Dict[str, Any] = {}
        self.turn_start_response: Dict[str, Any] = {}
        self.completed_turns: Dict[str, Dict[str, Any]] = {}
        self.notifications: List[Dict[str, Any]] = []
        self.server_requests: List[Dict[str, Any]] = []
        self.error_notifications: List[Dict[str, Any]] = []
        self.agent_message_deltas: Dict[str, List[str]] = {}
        self.completed_agent_messages: Dict[str, str] = {}
        self.plan: Dict[str, Any] = {}
        self.diffs: List[Dict[str, Any]] = []
        self.command_output: Dict[str, List[str]] = {}
        self.items: Dict[str, Dict[str, Any]] = {}
        self.files: List[Dict[str, str]] = []
        self.user_input_requests: List[Dict[str, Any]] = []
        self._open_thread_ids: set[str] = set()

    def is_running(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    def reset_turn_state(self) -> None:
        self.turn_start_response = {}
        self.completed_turns.clear()
        self.notifications.clear()
        self.server_requests.clear()
        self.error_notifications.clear()
        self.agent_message_deltas.clear()
        self.completed_agent_messages.clear()
        self.plan.clear()
        self.diffs.clear()
        self.command_output.clear()
        self.items.clear()
        self.files.clear()
        self.user_input_requests.clear()

    def set_event_callback(
        self,
        callback: Callable[[str, Dict[str, Any]], Awaitable[None] | None] | None,
    ) -> None:
        self.event_callback = callback

    async def start(self) -> None:
        if not self.command:
            raise ValueError("Codex app-server command is required")
        self.proc = await asyncio.create_subprocess_exec(
            *self.command,
            cwd=self.cwd,
            env=self.env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._reader_task = asyncio.create_task(self._read_stdout())
        self._stderr_task = asyncio.create_task(self._read_stderr())

    async def close(self) -> None:
        for future in list(self._pending.values()):
            if not future.done():
                future.cancel()
        self._pending.clear()
        for future in list(self._turn_waiters.values()):
            if not future.done():
                future.cancel()
        self._turn_waiters.clear()
        if self.proc is None:
            return
        if self.proc.stdin is not None:
            with contextlib.suppress(Exception):
                self.proc.stdin.close()
        if self.proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=3)
            except asyncio.TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    self.proc.kill()
                with contextlib.suppress(Exception):
                    await self.proc.wait()
        if self._reader_task is not None:
            with contextlib.suppress(Exception):
                await self._reader_task
        if self._stderr_task is not None:
            with contextlib.suppress(Exception):
                await self._stderr_task

    def has_open_thread(self, thread_id: str) -> bool:
        safe_thread_id = str(thread_id or "").strip()
        return bool(safe_thread_id and safe_thread_id in self._open_thread_ids)

    async def initialize(self) -> Dict[str, Any]:
        response = await self.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "ikaros",
                    "title": "Ikaros",
                    "version": "0.2.1",
                },
                "capabilities": {},
            },
        )
        self.initialize_response = dict(response or {})
        return self.initialize_response

    async def open_thread(self, *, existing_thread_id: str = "") -> tuple[str, bool]:
        safe_existing = str(existing_thread_id or "").strip()
        params = self._thread_params()
        if self.has_open_thread(safe_existing):
            return safe_existing, True
        if safe_existing:
            try:
                response = await self.request(
                    "thread/resume",
                    {
                        **params,
                        "threadId": safe_existing,
                    },
                )
                thread_id = self._extract_thread_id(response)
                self.thread_response = dict(response or {})
                resolved_thread_id = thread_id or safe_existing
                self._open_thread_ids.add(resolved_thread_id)
                return resolved_thread_id, True
            except JsonRpcError:
                pass

        response = await self.request("thread/start", params)
        thread_id = self._extract_thread_id(response)
        if not thread_id:
            raise RuntimeError("Codex app-server did not return a thread id")
        self.thread_response = dict(response or {})
        self._open_thread_ids.add(thread_id)
        return thread_id, False

    async def start_turn(
        self,
        *,
        thread_id: str,
        instruction: str,
        input_items: List[Dict[str, str]] | None = None,
    ) -> str:
        turn_input = list(input_items or [])
        if not turn_input:
            turn_input = [
                {
                    "type": "text",
                    "text": str(instruction or "").strip(),
                }
            ]
        params: Dict[str, Any] = {
            "threadId": str(thread_id or "").strip(),
            "input": turn_input,
        }
        if self.cwd:
            params["cwd"] = self.cwd
        if self.model:
            params["model"] = self.model
        if self.effort:
            params["effort"] = self.effort
        if self.approval_policy:
            params["approvalPolicy"] = self.approval_policy

        response = await self.request("turn/start", params)
        self.turn_start_response = dict(response or {})
        turn = dict(response.get("turn") or {})
        turn_id = str(turn.get("id") or "").strip()
        if not turn_id:
            raise RuntimeError("Codex app-server did not return a turn id")
        return turn_id

    async def wait_for_turn_completed(self, *, turn_id: str) -> Dict[str, Any]:
        safe_turn_id = str(turn_id or "").strip()
        completed = self.completed_turns.get(safe_turn_id)
        if completed is not None:
            return completed
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()
        self._turn_waiters[safe_turn_id] = future
        try:
            result = await asyncio.wait_for(future, timeout=self.timeout_sec)
        finally:
            self._turn_waiters.pop(safe_turn_id, None)
        return dict(result or {})

    async def interrupt_turn(self, *, thread_id: str, turn_id: str) -> None:
        await self.request(
            "turn/interrupt",
            {
                "threadId": str(thread_id or "").strip(),
                "turnId": str(turn_id or "").strip(),
            },
        )

    async def request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()
        async with self._request_lock:
            self._request_id += 1
            request_id = self._request_id
            self._pending[request_id] = future
            try:
                await self._send_json(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": str(method),
                        "params": dict(params or {}),
                    }
                )
            except Exception:
                self._pending.pop(request_id, None)
                if not future.done():
                    future.cancel()
                raise
        try:
            result = await asyncio.wait_for(future, timeout=self.request_timeout_sec)
        finally:
            self._pending.pop(request_id, None)
        if isinstance(result, Exception):
            raise result
        return dict(result or {})

    async def _send_json(self, payload: Dict[str, Any]) -> None:
        if self.proc is None or self.proc.stdin is None:
            raise RuntimeError("Codex app-server process is not running")
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        self.proc.stdin.write(line.encode("utf-8"))
        await self.proc.stdin.drain()

    async def _send_response(
        self,
        request_id: Any,
        *,
        result: Dict[str, Any] | None = None,
        error: Dict[str, Any] | None = None,
    ) -> None:
        payload: Dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
        if error is not None:
            payload["error"] = error
        else:
            payload["result"] = dict(result or {})
        await self._send_json(payload)

    async def _read_stdout(self) -> None:
        if self.proc is None or self.proc.stdout is None:
            return
        while True:
            line = await self.proc.stdout.readline()
            if not line:
                return
            raw = line.decode("utf-8", errors="replace").strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except Exception:
                self.stderr_text = _tail(self.stderr_text + "\n" + raw, MAX_LOG_CHARS)
                continue
            if isinstance(payload, dict):
                await self._handle_payload(payload)

    async def _read_stderr(self) -> None:
        if self.proc is None or self.proc.stderr is None:
            return
        while True:
            chunk = await self.proc.stderr.read(4096)
            if not chunk:
                return
            self.stderr_text = _tail(
                self.stderr_text + chunk.decode("utf-8", errors="replace"),
                MAX_LOG_CHARS,
            )

    async def _handle_payload(self, payload: Dict[str, Any]) -> None:
        if "method" in payload:
            method = str(payload.get("method") or "").strip()
            request_id = payload.get("id")
            params = payload.get("params")
            safe_params = dict(params) if isinstance(params, dict) else {}
            if request_id is None:
                await self._handle_notification(method, safe_params)
                return
            await self._handle_request(request_id, method, safe_params)
            return

        request_id = payload.get("id")
        if request_id is None:
            return
        try:
            safe_request_id = int(request_id)
        except Exception:
            return
        future = self._pending.get(safe_request_id)
        if future is None or future.done():
            return
        if "error" in payload and isinstance(payload.get("error"), dict):
            error = dict(payload.get("error") or {})
            future.set_result(
                JsonRpcError(
                    code=int(error.get("code") or -32603),
                    message=str(error.get("message") or "json-rpc error"),
                    data=error.get("data"),
                )
            )
            return
        future.set_result(dict(payload.get("result") or {}))

    async def _emit_event(self, event: str, payload: Dict[str, Any]) -> None:
        callback = self.event_callback
        if callback is None:
            return
        try:
            maybe_coro = callback(event, dict(payload or {}))
            if inspect.isawaitable(maybe_coro):
                await maybe_coro
        except Exception:
            return

    async def _handle_notification(self, method: str, params: Dict[str, Any]) -> None:
        notification = {
            "at": _now_iso(),
            "method": method,
            "params": dict(params or {}),
        }
        self.notifications.append(notification)
        self.notifications = self.notifications[-100:]

        if method == "item/agentMessage/delta":
            item_id = str(params.get("itemId") or "").strip()
            delta = str(params.get("delta") or "")
            if item_id and delta:
                self.agent_message_deltas.setdefault(item_id, []).append(delta)
                await self._emit_event(
                    "agent_message_delta",
                    {
                        "method": method,
                        "thread_id": str(params.get("threadId") or "").strip(),
                        "turn_id": str(params.get("turnId") or "").strip(),
                        "item_id": item_id,
                        "delta": delta,
                        "text": "".join(self.agent_message_deltas.get(item_id) or []),
                    },
                )
            return

        if method == "item/commandExecution/outputDelta":
            item_id = str(params.get("itemId") or "").strip()
            delta = str(params.get("delta") or "")
            if item_id and delta:
                self.command_output.setdefault(item_id, []).append(delta)
                await self._emit_event(
                    "command_output_delta",
                    {
                        "method": method,
                        "thread_id": str(params.get("threadId") or "").strip(),
                        "turn_id": str(params.get("turnId") or "").strip(),
                        "item_id": item_id,
                        "delta": delta,
                        "text": "".join(self.command_output.get(item_id) or []),
                    },
                )
            return

        if method == "item/completed":
            item = params.get("item")
            if isinstance(item, dict):
                item_id = str(item.get("id") or "").strip()
                rows = self._collect_files_from_item(
                    item,
                    thread_id=str(params.get("threadId") or "").strip(),
                )
                if item_id:
                    stored_item = dict(item)
                    if str(stored_item.get("type") or "") in {
                        "image_generation_call",
                        "image_generation_end",
                    }:
                        stored_item.pop("result", None)
                    self.items[item_id] = stored_item
                if rows:
                    await self._emit_event(
                        "generated_files",
                        {
                            "method": method,
                            "thread_id": str(params.get("threadId") or "").strip(),
                            "turn_id": str(params.get("turnId") or "").strip(),
                            "item_id": item_id,
                            "files": rows,
                        },
                    )
                if str(item.get("type") or "").strip() == "agentMessage":
                    text = str(item.get("text") or "")
                    if item_id and text:
                        self.completed_agent_messages[item_id] = text
                        await self._emit_event(
                            "agent_message_completed",
                            {
                                "method": method,
                                "thread_id": str(params.get("threadId") or "").strip(),
                                "turn_id": str(params.get("turnId") or "").strip(),
                                "item_id": item_id,
                                "text": text,
                            },
                        )
                else:
                    activity_text = self._activity_text_from_item(item)
                    if activity_text:
                        await self._emit_event(
                            "item_activity",
                            {
                                "method": method,
                                "thread_id": str(params.get("threadId") or "").strip(),
                                "turn_id": str(params.get("turnId") or "").strip(),
                                "item_id": item_id,
                                "item_type": str(item.get("type") or "").strip(),
                                "text": activity_text,
                            },
                        )
            return

        rows = self._collect_files_from_notification(method, params)
        if rows:
            await self._emit_event(
                "generated_files",
                {
                    "method": method,
                    "thread_id": str(params.get("threadId") or "").strip(),
                    "turn_id": str(params.get("turnId") or "").strip(),
                    "files": rows,
                },
            )
            return

        if method == "turn/completed":
            turn = dict(params.get("turn") or {})
            turn_id = str(turn.get("id") or params.get("turnId") or "").strip()
            if turn_id:
                self.completed_turns[turn_id] = turn
                future = self._turn_waiters.get(turn_id)
                if future is not None and not future.done():
                    future.set_result(turn)
            return

        if method == "turn/plan/updated":
            self.plan = dict(params or {})
            await self._emit_event("plan_updated", dict(params or {}))
            return

        if method == "turn/diff/updated":
            self.diffs.append(dict(params or {}))
            self.diffs = self.diffs[-20:]
            await self._emit_event("diff_updated", dict(params or {}))
            return

        if method == "error":
            self.error_notifications.append(dict(params or {}))
            self.error_notifications = self.error_notifications[-20:]

    async def _handle_request(
        self,
        request_id: Any,
        method: str,
        params: Dict[str, Any],
    ) -> None:
        self.server_requests.append(
            {"at": _now_iso(), "method": method, "params": dict(params or {})}
        )
        self.server_requests = self.server_requests[-100:]

        try:
            if method == "item/commandExecution/requestApproval":
                await self._send_response(
                    request_id,
                    result={
                        "decision": self._select_decision(
                            params.get("availableDecisions"),
                            default=self.approval_decision,
                        )
                    },
                )
                return

            if method == "item/fileChange/requestApproval":
                await self._send_response(
                    request_id,
                    result={"decision": self.approval_decision},
                )
                return

            if method in {"applyPatchApproval", "execCommandApproval"}:
                legacy = (
                    "approved"
                    if self.approval_decision in {"accept", "acceptForSession"}
                    else "denied"
                )
                await self._send_response(request_id, result={"decision": legacy})
                return

            if method == "item/permissions/requestApproval":
                permissions = params.get("permissions")
                await self._send_response(
                    request_id,
                    result={
                        "permissions": (
                            dict(permissions) if isinstance(permissions, dict) else {}
                        ),
                        "scope": "turn",
                    },
                )
                return

            if method == "item/tool/requestUserInput":
                self.user_input_requests.append(
                    {
                        "at": _now_iso(),
                        "method": method,
                        "params": dict(params or {}),
                    }
                )
                self.user_input_requests = self.user_input_requests[-20:]
                await self._send_response(request_id, result={"answers": {}})
                return

            await self._send_response(
                request_id,
                error={
                    "code": -32601,
                    "message": f"unsupported Codex app-server method: {method}",
                },
            )
        except Exception as exc:
            await self._send_response(
                request_id,
                error={"code": -32603, "message": str(exc)},
            )

    def _thread_params(self) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "cwd": self.cwd,
            "approvalPolicy": self.approval_policy,
            "sandbox": self.sandbox,
        }
        if self.model:
            params["model"] = self.model
        return params

    def _extract_thread_id(self, response: Dict[str, Any]) -> str:
        thread = response.get("thread")
        if isinstance(thread, dict):
            return str(thread.get("id") or "").strip()
        return ""

    def _select_decision(self, raw: Any, *, default: str) -> Any:
        available = [item for item in list(raw or []) if item]
        preferred = str(default or "accept").strip() or "accept"
        if preferred in available:
            return preferred
        if "accept" in available:
            return "accept"
        if "acceptForSession" in available:
            return "acceptForSession"
        if available:
            return available[0]
        return preferred

    def _activity_text_from_item(self, item: Dict[str, Any]) -> str:
        item_type = (
            str(item.get("type") or "").strip().replace("-", "_").lower()
        )
        compact_type = item_type.replace("_", "")
        if compact_type == "websearchcall":
            action = item.get("action")
            safe_action = dict(action) if isinstance(action, dict) else {}
            action_type = (
                str(safe_action.get("type") or "").strip().replace("-", "_").lower()
            )
            if action_type == "search":
                query = safe_action.get("query") or safe_action.get("queries") or ""
                if isinstance(query, list):
                    query = "；".join(str(item or "").strip() for item in query if item)
                query_text = str(query or "").strip()
                return f"搜索：{query_text}" if query_text else "搜索完成。"
            if action_type in {"open_page", "openpage"}:
                url = str(safe_action.get("url") or "").strip()
                return f"打开页面：{url}" if url else "页面读取完成。"
            return "网络检索完成。"

        if compact_type in {"commandexecution", "commandexecutioncall"}:
            command = item.get("command") or item.get("cmd") or ""
            if isinstance(command, list):
                command = " ".join(str(part or "").strip() for part in command if part)
            command_text = str(command or "").strip()
            return f"命令完成：{command_text}" if command_text else "命令执行完成。"

        return ""

    def _assistant_stdout(self) -> str:
        if self.completed_agent_messages:
            return "".join(self.completed_agent_messages.values()).strip()
        chunks: List[str] = []
        for item_chunks in self.agent_message_deltas.values():
            chunks.extend(item_chunks)
        return "".join(chunks).strip()

    def _error_message(self, turn: Dict[str, Any]) -> str:
        error = turn.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or "").strip()
            details = str(error.get("additionalDetails") or "").strip()
            return "\n".join([part for part in [message, details] if part]).strip()
        if self.error_notifications:
            error = self.error_notifications[-1].get("error")
            if isinstance(error, dict):
                return str(error.get("message") or error).strip()
            return str(error or self.error_notifications[-1]).strip()
        return ""

    def build_result(
        self,
        *,
        thread_id: str,
        turn_id: str,
        turn: Dict[str, Any],
        loaded_existing_thread: bool,
    ) -> Dict[str, Any]:
        safe_turn = dict(turn or {})
        status = str(safe_turn.get("status") or "").strip()
        stdout = self._assistant_stdout() or str(
            safe_turn.get("last_agent_message") or ""
        ).strip()
        error_message = self._error_message(safe_turn)
        ok = status == "completed"
        summary = _tail(
            stdout
            or error_message
            or ("" if ok else status)
            or ("" if ok else "Codex app-server round completed")
        )
        return {
            "ok": ok,
            "error_code": "" if ok else "command_failed",
            "message": "" if ok else summary,
            "command": _command_to_text(self.command),
            "cwd": self.cwd,
            "exit_code": 0 if ok else 1,
            "stdout": stdout,
            "stderr": _tail(self.stderr_text),
            "summary": summary,
            "backend": "",
            "transport": "app-server",
            "transport_session_id": str(thread_id or "").strip(),
            "thread_id": str(thread_id or "").strip(),
            "turn_id": str(turn_id or "").strip(),
            "loaded_existing_session": bool(loaded_existing_thread),
            "stop_reason": status,
            "turn": safe_turn,
            "initialize_response": dict(self.initialize_response or {}),
            "thread_response": dict(self.thread_response or {}),
            "turn_start_response": dict(self.turn_start_response or {}),
            "plan": dict(self.plan or {}),
            "diffs": list(self.diffs or []),
            "items": list(self.items.values()),
            "files": list(self.files or []),
            "command_output": {
                key: "".join(value)
                for key, value in dict(self.command_output or {}).items()
            },
            "server_requests": list(self.server_requests or []),
            "user_input_requests": list(self.user_input_requests or []),
            "notifications": list(self.notifications or []),
            "log_path": self.log_path,
        }

    def _collect_files_from_notification(
        self,
        method: str,
        params: Dict[str, Any],
    ) -> List[Dict[str, str]]:
        payload = params.get("payload")
        candidates: List[Dict[str, Any]] = []
        if isinstance(payload, dict):
            candidates.append(payload)
        if isinstance(params.get("item"), dict):
            candidates.append(dict(params.get("item") or {}))
        if not candidates and method in {"image_generation_end", "image_generation_call"}:
            candidates.append(dict(params or {}))
        rows: List[Dict[str, str]] = []
        for candidate in candidates:
            rows.extend(
                self._collect_files_from_item(
                    candidate,
                    thread_id=str(
                        params.get("threadId")
                        or candidate.get("thread_id")
                        or candidate.get("threadId")
                        or ""
                    ).strip(),
                )
            )
        return rows

    def _collect_files_from_item(
        self,
        item: Dict[str, Any],
        *,
        thread_id: str = "",
    ) -> List[Dict[str, str]]:
        rows = _extract_local_media_files(item)
        rows.extend(
            _extract_generated_image_files(
                item,
                thread_id=thread_id,
            )
        )
        if not rows:
            return []
        seen = {str(row.get("path") or "") for row in self.files}
        new_rows: List[Dict[str, str]] = []
        for row in rows:
            path_text = str(row.get("path") or "").strip()
            if not path_text or path_text in seen:
                continue
            self.files.append(row)
            new_rows.append(row)
            seen.add(path_text)
        self.files = self.files[-20:]
        return new_rows


def _image_extension(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return ".gif"
    return ".png"


def _decode_image_result(value: Any) -> bytes:
    if not isinstance(value, str):
        return b""
    text = value.strip()
    if not text:
        return b""
    if "," in text and text.lower().startswith("data:"):
        text = text.split(",", 1)[1]
    try:
        return base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        return b""


def _extract_generated_image_files(
    item: Dict[str, Any],
    *,
    thread_id: str = "",
) -> List[Dict[str, str]]:
    item_type = str(item.get("type") or "").strip()
    if item_type not in {"image_generation_call", "image_generation_end"}:
        return []
    data = _decode_image_result(item.get("result"))
    if not data:
        return []
    safe_thread_id = (
        str(thread_id or item.get("thread_id") or item.get("threadId") or "unknown")
        .strip()
        .replace("/", "_")
    )[:160] or "unknown"
    call_id = (
        str(item.get("id") or item.get("call_id") or item.get("callId") or "")
        .strip()
        .replace("/", "_")
    )
    if not call_id:
        call_id = "ig_" + hashlib.sha256(data).hexdigest()[:24]
    suffix = _image_extension(data)
    filename = call_id if call_id.lower().endswith(suffix) else f"{call_id}{suffix}"
    directory = Path.home() / ".codex" / "generated_images" / safe_thread_id
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path_obj = (directory / filename).resolve()
        if not path_obj.exists() or path_obj.read_bytes() != data:
            path_obj.write_bytes(data)
    except Exception:
        return []
    return [
        {
            "kind": "photo",
            "path": str(path_obj),
            "filename": path_obj.name,
            "caption": "",
        }
    ]


def _extract_local_media_files(value: Any) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    seen: set[str] = set()

    def visit(node: Any, key_hint: str = "") -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                visit(child, str(key or ""))
            return
        if isinstance(node, list):
            for child in node:
                visit(child, key_hint)
            return
        if not isinstance(node, str):
            return
        if key_hint not in PATH_KEYS:
            return
        path_text = node.strip()
        if not path_text:
            return
        try:
            path_obj = Path(path_text).expanduser().resolve()
        except Exception:
            return
        suffix = path_obj.suffix.lower()
        kind = MEDIA_EXTENSIONS.get(suffix)
        if not kind and suffix in DOCUMENT_EXTENSIONS:
            kind = "document"
        if not kind or not path_obj.exists() or not path_obj.is_file():
            return
        resolved = str(path_obj)
        if resolved in seen:
            return
        seen.add(resolved)
        rows.append(
            {
                "kind": kind,
                "path": resolved,
                "filename": path_obj.name,
                "caption": "",
            }
        )

    visit(value)
    return rows


async def run_codex_app_server_backend(
    *,
    command: List[str],
    cwd: str,
    instruction: str,
    timeout_sec: int = 1800,
    existing_thread_id: str = "",
    log_path: str = "",
    env: Dict[str, str] | None = None,
    model: str = "",
    effort: str = "",
    approval_policy: str = "never",
    sandbox: str = "workspace-write",
    approval_decision: str = "accept",
) -> Dict[str, Any]:
    safe_instruction = str(instruction or "").strip()
    safe_cwd = str(cwd or "").strip()
    safe_command = [str(item) for item in list(command or []) if str(item)]
    if not safe_instruction:
        return {
            "ok": False,
            "error_code": "invalid_args",
            "message": "instruction is required",
        }
    if not safe_cwd:
        return {
            "ok": False,
            "error_code": "invalid_args",
            "message": "cwd is required",
        }
    if not safe_command:
        return {
            "ok": False,
            "error_code": "invalid_args",
            "message": "Codex app-server command is required",
        }

    client = CodexAppServerClient(
        command=safe_command,
        cwd=safe_cwd,
        env=dict(env or os.environ),
        timeout_sec=max(30, int(timeout_sec or 0)),
        log_path=log_path,
        model=model,
        effort=effort,
        approval_policy=approval_policy,
        sandbox=sandbox,
        approval_decision=approval_decision,
    )
    thread_id = ""
    turn_id = ""
    try:
        await client.start()
        await client.initialize()
        thread_id, loaded_existing = await client.open_thread(
            existing_thread_id=existing_thread_id
        )
        turn_id = await client.start_turn(
            thread_id=thread_id,
            instruction=safe_instruction,
        )
        turn = await client.wait_for_turn_completed(turn_id=turn_id)
        result = client.build_result(
            thread_id=thread_id,
            turn_id=turn_id,
            turn=turn,
            loaded_existing_thread=loaded_existing,
        )
        _append_app_server_log(
            log_path=log_path,
            command=safe_command,
            cwd=safe_cwd,
            thread_id=thread_id,
            turn_id=turn_id,
            status=str(result.get("stop_reason") or ""),
            stdout=str(result.get("stdout") or ""),
            stderr=str(result.get("stderr") or ""),
            timed_out=False,
        )
        return result
    except FileNotFoundError:
        return {
            "ok": False,
            "error_code": "command_not_found",
            "message": f"command not found: {safe_command[0]}",
            "command": _command_to_text(safe_command),
            "cwd": safe_cwd,
            "transport": "app-server",
            "transport_session_id": thread_id,
            "log_path": log_path,
        }
    except asyncio.TimeoutError:
        with contextlib.suppress(Exception):
            if thread_id and turn_id:
                await client.interrupt_turn(thread_id=thread_id, turn_id=turn_id)
        result = {
            "ok": False,
            "error_code": "timeout",
            "message": f"Codex app-server round timed out after {timeout_sec}s",
            "command": _command_to_text(safe_command),
            "cwd": safe_cwd,
            "stdout": client._assistant_stdout(),
            "stderr": _tail(client.stderr_text),
            "summary": _tail(client._assistant_stdout() or client.stderr_text),
            "transport": "app-server",
            "transport_session_id": thread_id,
            "thread_id": thread_id,
            "turn_id": turn_id,
            "log_path": log_path,
        }
        _append_app_server_log(
            log_path=log_path,
            command=safe_command,
            cwd=safe_cwd,
            thread_id=thread_id,
            turn_id=turn_id,
            status="timeout",
            stdout=str(result.get("stdout") or ""),
            stderr=str(result.get("stderr") or ""),
            timed_out=True,
        )
        return result
    except JsonRpcError as exc:
        return {
            "ok": False,
            "error_code": "command_failed",
            "message": exc.message,
            "command": _command_to_text(safe_command),
            "cwd": safe_cwd,
            "stdout": client._assistant_stdout(),
            "stderr": _tail(client.stderr_text),
            "summary": _tail(exc.message),
            "transport": "app-server",
            "transport_session_id": thread_id,
            "thread_id": thread_id,
            "turn_id": turn_id,
            "log_path": log_path,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "exec_prepare_failed",
            "message": str(exc),
            "command": _command_to_text(safe_command),
            "cwd": safe_cwd,
            "stdout": client._assistant_stdout(),
            "stderr": _tail(client.stderr_text),
            "summary": _tail(str(exc)),
            "transport": "app-server",
            "transport_session_id": thread_id,
            "thread_id": thread_id,
            "turn_id": turn_id,
            "log_path": log_path,
        }
    finally:
        with contextlib.suppress(Exception):
            await client.close()
