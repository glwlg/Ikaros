from __future__ import annotations

import asyncio
import inspect
import json
from types import SimpleNamespace
from typing import Any, Awaitable, Callable


ToolExecutor = Callable[[str, dict[str, Any]], Any]
EventCallback = Callable[[str, dict[str, Any]], Any]


def build_agent_tools(
    *,
    tools: list[Any] | None,
    tool_executor: ToolExecutor | None,
    event_callback: EventCallback | None = None,
    runtime_state: dict[str, Any] | None = None,
    sdk: Any | None = None,
) -> list[Any]:
    if not tools or tool_executor is None:
        return []

    function_tool_cls = (sdk or _load_agents_tool_sdk()).FunctionTool
    output: list[Any] = []
    seen: set[str] = set()
    for raw_tool in tools:
        definition = _normalize_tool_definition(raw_tool)
        name = definition["name"]
        if not name or name in seen:
            continue
        seen.add(name)
        output.append(
            function_tool_cls(
                name=name,
                description=definition["description"],
                params_json_schema=definition["parameters"],
                on_invoke_tool=_make_tool_invoker(
                    tool_name=name,
                    tool_executor=tool_executor,
                    event_callback=event_callback,
                    runtime_state=runtime_state,
                ),
                strict_json_schema=False,
            )
        )
    return output


def _normalize_tool_definition(tool: Any) -> dict[str, Any]:
    if isinstance(tool, dict):
        name = str(tool.get("name") or "").strip()
        description = str(tool.get("description") or "")
        parameters = tool.get("parameters")
    else:
        name = str(getattr(tool, "name", "") or "").strip()
        description = str(getattr(tool, "description", "") or "")
        parameters = getattr(tool, "parameters", None)

    if not isinstance(parameters, dict):
        parameters = {"type": "object", "properties": {}}
    return {
        "name": name,
        "description": description,
        "parameters": parameters,
    }


def _make_tool_invoker(
    *,
    tool_name: str,
    tool_executor: ToolExecutor,
    event_callback: EventCallback | None,
    runtime_state: dict[str, Any] | None,
) -> Callable[[Any, str], Awaitable[str]]:
    async def invoke_tool(_ctx: Any, raw_args: str) -> str:
        args, parse_error = _parse_tool_args(raw_args)
        await _emit(
            event_callback,
            "tool_call_started",
            {"turn": 1, "name": tool_name, "args": args},
        )
        if parse_error:
            result = {
                "ok": False,
                "error_code": "invalid_json_args",
                "message": parse_error,
                "failure_mode": "recoverable",
            }
            await _emit_tool_finished(
                event_callback,
                tool_name=tool_name,
                tool_result=result,
            )
            return _tool_content(result)

        try:
            maybe_result = tool_executor(tool_name, args)
            tool_result = (
                await maybe_result
                if inspect.isawaitable(maybe_result)
                else maybe_result
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            tool_result = {
                "ok": False,
                "error_code": "system_error",
                "message": str(exc),
                "failure_mode": "recoverable",
            }

        directive = await _emit_tool_finished(
            event_callback,
            tool_name=tool_name,
            tool_result=tool_result,
        )
        if isinstance(runtime_state, dict) and isinstance(directive, dict):
            if directive.get("stop") is True:
                runtime_state["terminal_stop_text"] = str(
                    directive.get("final_text") or ""
                ).strip()
        return _tool_content(tool_result)

    return invoke_tool


def _parse_tool_args(raw_args: str) -> tuple[dict[str, Any], str]:
    payload = str(raw_args or "").strip()
    if not payload:
        return {}, ""
    try:
        loaded = json.loads(payload)
    except Exception:
        return {}, "工具参数不是合法 JSON 对象"
    if not isinstance(loaded, dict):
        return {}, "工具参数不是合法 JSON 对象"
    return _normalize_empty_strings(loaded), ""


def _normalize_empty_strings(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _normalize_empty_strings(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_empty_strings(item) for item in value]
    if isinstance(value, str) and value == "":
        return None
    return value


async def _emit_tool_finished(
    event_callback: EventCallback | None,
    *,
    tool_name: str,
    tool_result: Any,
) -> Any:
    terminal_text, terminal_ui, terminal_payload = _extract_terminal_artifacts(
        tool_result
    )
    return await _emit(
        event_callback,
        "tool_call_finished",
        {
            "turn": 1,
            "name": tool_name,
            "ok": _tool_result_ok(tool_result),
            "summary": _summarize_tool_result(tool_result),
            "terminal": bool(
                isinstance(tool_result, dict)
                and (
                    tool_result.get("terminal")
                    or tool_result.get("task_outcome") == "done"
                )
            ),
            "task_outcome": (
                str(tool_result.get("task_outcome") or "").strip().lower()
                if isinstance(tool_result, dict)
                else ""
            ),
            "terminal_text": terminal_text,
            "terminal_text_preview": terminal_text[:200],
            "terminal_ui": terminal_ui,
            "terminal_payload": terminal_payload,
            "data": (
                dict(tool_result.get("data"))
                if isinstance(tool_result, dict)
                and isinstance(tool_result.get("data"), dict)
                else {}
            ),
            "failure_mode": (
                str(tool_result.get("failure_mode") or "").strip().lower()
                if isinstance(tool_result, dict)
                else ""
            ),
            "history_visibility": (
                str(tool_result.get("history_visibility") or "").strip()
                if isinstance(tool_result, dict)
                else ""
            ),
        },
    )


async def _emit(
    event_callback: EventCallback | None,
    event: str,
    payload: dict[str, Any],
) -> Any:
    if event_callback is None:
        return None
    maybe_coro = event_callback(event, payload)
    if inspect.isawaitable(maybe_coro):
        return await maybe_coro
    return maybe_coro


def _tool_content(tool_result: Any) -> str:
    return json.dumps(
        {"result": _sanitize_tool_result_for_history(tool_result)},
        ensure_ascii=False,
        default=str,
    )


def _tool_result_ok(tool_result: Any) -> bool:
    if isinstance(tool_result, dict):
        if "ok" in tool_result:
            return bool(tool_result.get("ok"))
        if tool_result.get("success") is False:
            return False
        text = str(tool_result.get("message") or tool_result.get("text") or "")
        lowered = text.lower().strip()
        return not (lowered.startswith("error") or lowered.startswith("❌"))
    if isinstance(tool_result, str):
        lowered = tool_result.lower().strip()
        return not (
            lowered.startswith("error")
            or lowered.startswith("❌")
            or "traceback" in lowered
        )
    return tool_result is not None


def _summarize_tool_result(tool_result: Any) -> str:
    if isinstance(tool_result, dict):
        for key in ("text", "result", "message", "summary"):
            value = str(tool_result.get(key) or "").strip()
            if value:
                return value[:200]
        return str(tool_result)[:200]
    return str(tool_result)[:200]


def _extract_terminal_artifacts(
    tool_result: Any,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    text = ""
    ui: dict[str, Any] = {}
    payload: dict[str, Any] = {}
    if not isinstance(tool_result, dict):
        text = str(tool_result or "").strip()
        return text, ui, {"text": text} if text else {}

    raw_payload = tool_result.get("payload")
    if isinstance(raw_payload, dict):
        payload = dict(raw_payload)
    ui_candidate = tool_result.get("ui")
    if not isinstance(ui_candidate, dict) and isinstance(payload.get("ui"), dict):
        ui_candidate = payload.get("ui")
    if isinstance(ui_candidate, dict):
        ui = dict(ui_candidate)

    for value in (
        payload.get("text"),
        tool_result.get("text"),
        tool_result.get("result"),
        tool_result.get("message"),
        tool_result.get("summary"),
    ):
        rendered = str(value or "").strip()
        if rendered:
            text = rendered
            break
    if text and "text" not in payload:
        payload["text"] = text
    if ui and "ui" not in payload:
        payload["ui"] = ui
    if "completion_signal" not in payload and isinstance(
        tool_result.get("completion_signal"), dict
    ):
        payload["completion_signal"] = dict(tool_result.get("completion_signal") or {})
    return text, ui, payload


def _sanitize_tool_result_for_history(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _sanitize_tool_result_for_history(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_tool_result_for_history(item) for item in value[:50]]
    if isinstance(value, tuple):
        return [_sanitize_tool_result_for_history(item) for item in list(value)[:50]]
    if isinstance(value, (bytes, bytearray)):
        return f"<binary:{len(value)} bytes>"
    if isinstance(value, str) and len(value) > 64_000:
        return value[:64_000].rstrip() + "\n...[truncated]"
    return value


def _load_agents_tool_sdk() -> Any:
    try:
        from agents import FunctionTool  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - exercised through runtime error
        raise RuntimeError(
            "OpenAI Agents SDK is unavailable. Install the `openai-agents` dependency."
        ) from exc

    return SimpleNamespace(FunctionTool=FunctionTool)
