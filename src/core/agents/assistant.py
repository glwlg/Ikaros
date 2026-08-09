from __future__ import annotations

import inspect
import json
import os
from typing import Any, AsyncIterator, Callable

from core.agents.runtime import (
    build_agent_model,
    looks_like_unexecuted_tool_call,
    looks_like_pending_action,
    parse_legacy_dsml_tool_calls,
    resolve_agents_model_config,
    sanitize_visible_assistant_text,
)
from core.agents.tools import build_agent_tools
from services.openai_adapter import build_messages


def to_agents_sdk_input(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Convert OpenAI Chat Completions content blocks into Agents SDK input items.

    `build_messages` emits Chat Completions parts (`text`, `image_url`, `file`).
    Agents SDK's ChatCompletions converter expects Responses-style parts
    (`input_text`, `input_image`, `input_file`) and raises UserError otherwise.
    """
    converted: list[dict[str, Any]] = []
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").strip() or "user"
        content = message.get("content")
        if isinstance(content, str) or content is None:
            converted.append(
                {"role": role, "content": content if content is not None else ""}
            )
            continue
        if not isinstance(content, list):
            converted.append({"role": role, "content": str(content)})
            continue

        blocks: list[dict[str, Any]] = []
        for block in content:
            mapped = _map_content_block_for_agents_sdk(block)
            if mapped is not None:
                blocks.append(mapped)
        if not blocks:
            continue
        if len(blocks) == 1 and blocks[0].get("type") == "input_text":
            converted.append(
                {"role": role, "content": str(blocks[0].get("text") or "")}
            )
            continue
        converted.append({"role": role, "content": blocks})
    return converted


def _map_content_block_for_agents_sdk(block: Any) -> dict[str, Any] | None:
    if not isinstance(block, dict):
        return None

    block_type = str(block.get("type") or "").strip()
    if block_type in {"input_text", "input_image", "input_audio", "input_file"}:
        return dict(block)

    if block_type in {"text", "output_text"}:
        text = str(block.get("text") or "")
        if not text:
            return None
        return {"type": "input_text", "text": text}

    if block_type == "image_url":
        image_url = block.get("image_url")
        url = ""
        detail = "auto"
        if isinstance(image_url, dict):
            url = str(image_url.get("url") or "").strip()
            detail = str(image_url.get("detail") or "auto").strip() or "auto"
        else:
            url = str(image_url or "").strip()
        if not url:
            return None
        return {"type": "input_image", "image_url": url, "detail": detail}

    if block_type == "file":
        file_obj = block.get("file") if isinstance(block.get("file"), dict) else {}
        file_data = str(file_obj.get("file_data") or "").strip()
        if not file_data:
            return None
        mapped: dict[str, Any] = {"type": "input_file", "file_data": file_data}
        filename = str(file_obj.get("filename") or "").strip()
        if filename:
            mapped["filename"] = filename
        return mapped

    return None


class AgentsSdkAssistantRuntime:
    """Stream Ikaros chat through OpenAI Agents SDK."""

    def __init__(
        self,
        *,
        runner: Any | None = None,
        agent_cls: Any | None = None,
        model_settings_cls: Any | None = None,
        model_builder: Callable[..., Any] = build_agent_model,
    ):
        self._runner = runner
        self._agent_cls = agent_cls
        self._model_settings_cls = model_settings_cls
        self._model_builder = model_builder

    async def generate_response_stream(
        self,
        message_history: list,
        tools: list | None = None,
        tool_executor: Callable[[str, dict[str, Any]], Any] | None = None,
        system_instruction: str | None = None,
        event_callback: Callable[[str, dict[str, Any]], Any] | None = None,
    ) -> AsyncIterator[str]:
        sdk = self._load_assistant_sdk()
        await self._emit(
            event_callback, "turn_start", {"turn": 1, "kernel_provider": "agents_sdk"}
        )

        model_config = resolve_agents_model_config()
        model = self._model_builder(model_config)
        runtime_state: dict[str, Any] = {}

        async def _agent_event_callback(event: str, payload: dict[str, Any]) -> Any:
            if event == "tool_call_started":
                runtime_state["tool_call_seen"] = True
            return await self._emit(event_callback, event, payload)

        agent_tools = build_agent_tools(
            tools=tools,
            tool_executor=tool_executor,
            event_callback=_agent_event_callback,
            runtime_state=runtime_state,
        )
        agent_tool_by_name = {
            str(getattr(tool, "name", "") or "").strip(): tool
            for tool in agent_tools
            if str(getattr(tool, "name", "") or "").strip()
        }
        extra_body = {
            # Some OpenAI-compatible DeepSeek endpoints use this flag to
            # disable hidden thinking. Keep the existing vLLM-compatible form
            # as well because different gateways honor different shapes.
            "chat_template_kwargs": {"enable_thinking": False},
        }
        official_openai_endpoint = str(
            model_config.provider or ""
        ).strip().lower() == "openai" and (
            not str(model_config.base_url or "").strip()
            or "api.openai.com" in str(model_config.base_url or "").lower()
        )
        if not official_openai_endpoint and not bool(
            getattr(model_config, "reasoning", False)
        ):
            extra_body["thinking"] = {"type": "disabled"}
        # Per-model reasoning effort from models.json. Sent via extra_body so
        # OpenAI-compatible gateways accepting non-standard levels (xhigh,
        # ultra, ...) work; the Responses API path uses SDK defaults instead.
        reasoning_effort = str(
            getattr(model_config, "reasoning_effort", "") or ""
        ).strip()
        responses_api_path = official_openai_endpoint and bool(
            getattr(model_config, "force_responses_model", False)
        )
        if (
            reasoning_effort
            and bool(getattr(model_config, "reasoning", False))
            and not responses_api_path
        ):
            extra_body["reasoning_effort"] = reasoning_effort
        model_settings_kwargs: dict[str, Any] = {
            "temperature": _env_float("OPENAI_TEMPERATURE"),
            "tool_choice": "auto" if agent_tools else None,
            "extra_body": extra_body,
        }
        model_settings = sdk.ModelSettings(
            **model_settings_kwargs,
        )
        agent = sdk.Agent(
            name="Ikaros Assistant",
            instructions=str(system_instruction or "").strip(),
            model=model,
            model_settings=model_settings,
            tools=agent_tools,
        )
        base_input = to_agents_sdk_input(build_messages(contents=message_history))

        async def _run_once(input_items: list[dict[str, Any]]) -> str:
            result = sdk.Runner.run_streamed(
                agent,
                input=input_items,
                max_turns=_env_int("AI_TOOL_MAX_TURNS", 40),
            )
            output_text_chunks: list[str] = []
            raw_output_text_chunks: list[str] = []
            async for event in result.stream_events():
                delta = _extract_output_text_delta(event)
                if delta:
                    raw_output_text_chunks.append(delta)
                    if looks_like_unexecuted_tool_call(delta):
                        continue
                    output_text_chunks.append(delta)
                    continue
            result_text = str(getattr(result, "final_output", "") or "").strip()
            if not result_text:
                result_text = "".join(raw_output_text_chunks or output_text_chunks)
            return sanitize_visible_assistant_text(result_text)

        final_text = await _run_once(base_input)

        # DeepSeek-compatible gateways sometimes return their native DSML tool
        # syntax as plain assistant text. Execute those calls through the same
        # FunctionTool wrapper used by the Agents SDK, then give the model the
        # result in a fresh turn. This keeps the channel delivery side effects
        # and tool event bookkeeping identical to a structured tool call.
        legacy_dsml_signatures: set[str] = set()
        for _legacy_round in range(2):
            if runtime_state.get("tool_call_seen") and not legacy_dsml_signatures:
                break
            legacy_calls = parse_legacy_dsml_tool_calls(
                final_text,
                allowed_tool_names=set(agent_tool_by_name),
            )
            if not legacy_calls:
                break
            fresh_calls: list[dict[str, Any]] = []
            for call in legacy_calls:
                signature = json.dumps(
                    {
                        "name": call.get("name"),
                        "args": call.get("args") or {},
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                )
                if signature in legacy_dsml_signatures:
                    continue
                legacy_dsml_signatures.add(signature)
                fresh_calls.append(call)
            if not fresh_calls:
                break

            tool_results: list[str] = []
            for call in fresh_calls:
                name = str(call.get("name") or "").strip()
                tool = agent_tool_by_name.get(name)
                if tool is None:
                    continue
                raw_args = json.dumps(
                    call.get("args") if isinstance(call.get("args"), dict) else {},
                    ensure_ascii=False,
                )
                result_text = await tool.on_invoke_tool(None, raw_args)
                tool_results.append(f"工具 `{name}` 返回：{str(result_text)[:12000]}")

            terminal_stop_text = str(
                runtime_state.get("terminal_stop_text") or ""
            ).strip()
            if terminal_stop_text:
                final_text = terminal_stop_text
                break
            if not tool_results:
                break

            retry_input = list(base_input)
            retry_input.extend(
                [
                    {
                        "role": "assistant",
                        "content": "（运行时已解析并执行上一条旧版 DSML 工具调用。）",
                    },
                    {
                        "role": "user",
                        "content": (
                            "系统提示：上一条回复使用了旧版 DSML 工具格式，运行时已经实际执行。"
                            "请直接基于下面的工具结果回复用户；不要再次输出 DSML 标记，"
                            "如结果包含用户要求发送的图片或文件路径，必须继续调用 `send_message` 立即发送，"
                            "不要只报告路径；如仍需其他操作请调用可用的标准工具。\n"
                            + "\n".join(tool_results)
                        ),
                    },
                ]
            )
            final_text = await _run_once(retry_input)

        # Models occasionally emit a progress promise as their final answer
        # instead of invoking the visible tool (notably for media/download
        # requests). Give them one explicit execution-only continuation. This
        # path is limited to a single retry and only applies before any tool has
        # actually run, so it cannot duplicate side effects.
        if (
            agent_tools
            and not runtime_state.get("tool_call_seen")
            and looks_like_pending_action(
                _latest_user_text(message_history),
                final_text,
            )
        ):
            runtime_state["tool_call_seen"] = False
            retry_input = list(base_input)
            retry_input.extend(
                [
                    {"role": "assistant", "content": final_text},
                    {
                        "role": "user",
                        "content": (
                            "系统提示：上一条回复只承诺了动作，但没有调用任何工具。"
                            "不要再次输出计划、承诺或‘正在处理’；必须立即调用与用户请求匹配的可用工具并根据工具结果回复。"
                            "如果确实没有可用工具，明确说明无法完成，不要声称已经开始。"
                        ),
                    },
                ]
            )
            final_text = await _run_once(retry_input)
        terminal_stop_text = str(runtime_state.get("terminal_stop_text") or "").strip()
        if terminal_stop_text:
            final_text = terminal_stop_text
        elif looks_like_unexecuted_tool_call(final_text):
            final_text = "⚠️ 模型返回了未执行的工具调用，已拦截。"
            await self._emit(
                event_callback,
                "final_response",
                {
                    "turn": 1,
                    "text_preview": final_text,
                    "text": final_text,
                    "completion_signal": {
                        "explicit": True,
                        "status": "failed",
                        "tool_name": "agents_sdk_sanitizer",
                    },
                    "source": "agents_sdk_sanitizer",
                },
            )
            yield final_text
            return

        if final_text:
            await self._emit(
                event_callback,
                "final_response",
                {
                    "turn": 1,
                    "text_preview": final_text.replace("\n", " ")[:200],
                    "text": final_text,
                    "source": "agents_sdk",
                },
            )
            yield final_text

    def _load_assistant_sdk(self) -> Any:
        if self._runner and self._agent_cls and self._model_settings_cls:
            return _InjectedAssistantSdk(
                Agent=self._agent_cls,
                Runner=self._runner,
                ModelSettings=self._model_settings_cls,
            )
        try:
            from agents import Agent, ModelSettings, Runner  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover - exercised through runtime error
            raise RuntimeError(
                "OpenAI Agents SDK is unavailable. Install the `openai-agents` dependency."
            ) from exc
        return _InjectedAssistantSdk(
            Agent=Agent,
            Runner=Runner,
            ModelSettings=ModelSettings,
        )

    async def _emit(
        self,
        event_callback: Callable[[str, dict[str, Any]], Any] | None,
        event: str,
        payload: dict[str, Any],
    ) -> Any:
        if event_callback is None:
            return None
        maybe_coro = event_callback(event, payload)
        if inspect.isawaitable(maybe_coro):
            return await maybe_coro
        return maybe_coro


class _InjectedAssistantSdk:
    def __init__(self, *, Agent: Any, Runner: Any, ModelSettings: Any):
        self.Agent = Agent
        self.Runner = Runner
        self.ModelSettings = ModelSettings


def _extract_output_text_delta(event: Any) -> str:
    if str(getattr(event, "type", "") or "") != "raw_response_event":
        return ""
    data = getattr(event, "data", None)
    event_type = _read_value(data, "type")
    if event_type != "response.output_text.delta":
        return ""
    return str(_read_value(data, "delta") or "")


def _read_value(item: Any, key: str) -> Any:
    if item is None:
        return None
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def _latest_user_text(message_history: list[Any]) -> str:
    """Extract text from the most recent user item for execution guards."""

    for item in reversed(list(message_history or [])):
        if not isinstance(item, dict) or str(item.get("role") or "").lower() != "user":
            continue
        parts = item.get("parts")
        if isinstance(parts, list):
            texts = [
                str(part.get("text") or "").strip()
                for part in parts
                if isinstance(part, dict) and str(part.get("text") or "").strip()
            ]
            if texts:
                return "\n".join(texts)
        content = item.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            texts = [
                str(part.get("text") or "").strip()
                for part in content
                if isinstance(part, dict) and str(part.get("text") or "").strip()
            ]
            if texts:
                return "\n".join(texts)
    return ""


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except Exception:
        return default


def _env_float(name: str) -> float | None:
    raw = str(os.getenv(name, "") or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except Exception:
        return None
