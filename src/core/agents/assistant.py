from __future__ import annotations

import inspect
import os
from typing import Any, AsyncIterator, Callable

from core.agents.runtime import (
    build_agent_model,
    looks_like_unexecuted_tool_call,
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
            converted.append({"role": role, "content": content if content is not None else ""})
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
        agent_tools = build_agent_tools(
            tools=tools,
            tool_executor=tool_executor,
            event_callback=event_callback,
            runtime_state=runtime_state,
        )
        model_settings = sdk.ModelSettings(
            temperature=_env_float("OPENAI_TEMPERATURE"),
            tool_choice="auto" if agent_tools else None,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        agent = sdk.Agent(
            name="Ikaros Assistant",
            instructions=str(system_instruction or "").strip(),
            model=model,
            model_settings=model_settings,
            tools=agent_tools,
        )
        result = sdk.Runner.run_streamed(
            agent,
            input=to_agents_sdk_input(build_messages(contents=message_history)),
            max_turns=_env_int("AI_TOOL_MAX_TURNS", 40),
        )

        output_text_chunks: list[str] = []
        async for event in result.stream_events():
            delta = _extract_output_text_delta(event)
            if delta:
                if looks_like_unexecuted_tool_call(delta):
                    continue
                output_text_chunks.append(delta)
                continue

        final_text = sanitize_visible_assistant_text(
            str(getattr(result, "final_output", "") or "".join(output_text_chunks))
        )
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
