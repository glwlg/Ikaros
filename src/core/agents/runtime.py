from __future__ import annotations

import html
import json
import logging
import os
import re
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Callable


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentsModelConfig:
    """Resolved model settings for the Agents SDK bridge."""

    api_key: str
    base_url: str | None
    model: str
    provider: str = "openai"
    reasoning: bool = False
    force_responses_model: bool = False
    tracing_disabled: bool = True
    timeout: float = 600.0
    headers: dict[str, str] | None = None


_UNEXECUTED_TOOL_PATTERNS = [
    re.compile(r"<\s*/?\s*tool_call\b", re.IGNORECASE),
    re.compile(r'"tool_calls"\s*:', re.IGNORECASE),
    re.compile(r'"function_call"\s*:', re.IGNORECASE),
    re.compile(r"\btool_calls\s*=\s*\[", re.IGNORECASE),
    re.compile(r"<\s*/?\s*[|｜]\s*/?\s*DSML\s*[|｜]\s*>", re.IGNORECASE),
]

_VISIBLE_THINKING_PREFIXES = [
    re.compile(r"^\s*the user\b.*", re.IGNORECASE),
    re.compile(r"^\s*we need to\b.*", re.IGNORECASE),
    re.compile(r"^\s*i need to\b.*", re.IGNORECASE),
    re.compile(r"^\s*i should\b.*", re.IGNORECASE),
    re.compile(r"^\s*let me\b.*", re.IGNORECASE),
    re.compile(r"^\s*workflow\b.*", re.IGNORECASE),
    re.compile(r"^\s*plan\s*[:：].*", re.IGNORECASE),
    re.compile(r"^\s*analysis\s*[:：].*", re.IGNORECASE),
]

_ACTION_REQUEST_MARKERS = (
    "下载",
    "发给我",
    "发送",
    "获取",
    "抓取",
    "提取",
    "查询",
    "搜索",
    "分析",
    "执行",
    "安装",
    "部署",
    "发布",
    "生成",
    "读取",
    "打开",
    "检查",
    "转发",
    "保存",
    "找出",
)

_PENDING_ACTION_RESPONSE_PATTERNS = [
    re.compile(r"我先.{0,40}(看看|查看|找|查|处理|弄|分析|确认)", re.IGNORECASE),
    re.compile(r"我(?:去|来).{0,40}(看看|查看|找|查|处理|弄|分析|确认)", re.IGNORECASE),
    re.compile(r"正在.{0,50}(下载|获取|抓取|处理|分析|查看|查找)", re.IGNORECASE),
    re.compile(r"稍后|稍等|等我|马上帮你", re.IGNORECASE),
]


def looks_like_unexecuted_tool_call(text: str) -> bool:
    payload = str(text or "")
    if not payload.strip():
        return False
    return any(pattern.search(payload) for pattern in _UNEXECUTED_TOOL_PATTERNS)


_DSML_MARKER_RE = re.compile(
    r"<\s*/?\s*[|｜]\s*/?\s*DSML\s*[|｜]\s*>", re.IGNORECASE
)
_DSML_ATTRIBUTE_RE = re.compile(
    r"(?P<key>[A-Za-z_][\w-]*)\s*=\s*(?:\"(?P<double>[^\"]*)\"|'(?P<single>[^']*)'|(?P<bare>[^\s>]+))",
    re.IGNORECASE,
)


def parse_legacy_dsml_tool_calls(
    text: str,
    *,
    allowed_tool_names: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Parse DeepSeek's legacy DSML tool-call text emitted by some gateways.

    A few OpenAI-compatible proxies expose DeepSeek's native tool template as
    assistant text instead of converting it to ``message.tool_calls``.  The
    format has appeared both as XML-like tags (``invoke name=...``) and as
    marker-delimited fields (``invoke / name / bash``), so this parser accepts
    both shapes and returns only calls that are present in the injected tool
    set.
    """

    payload = str(text or "").strip()
    if not payload or not _DSML_MARKER_RE.search(payload):
        return []

    # DeepSeek commonly uses full-width vertical bars in the token spelling.
    normalized = payload.replace("｜", "|")
    parts = [part.strip() for part in _DSML_MARKER_RE.split(normalized) if part.strip()]
    if not parts:
        return []

    allowed = {
        str(name or "").strip()
        for name in (allowed_tool_names or set())
        if str(name or "").strip()
    }
    calls: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    index = 0
    while index < len(parts):
        part = parts[index].strip()
        lower = part.lower().strip(" >")
        if lower in {"tool_calls", "function_calls"}:
            index += 1
            continue

        if lower.startswith("invoke"):
            header, inline = _split_dsml_header(part, "invoke")
            attrs = _parse_dsml_attributes(header)
            name = str(attrs.get("name") or "").strip()
            has_delimited_name = (
                not name
                and index + 2 < len(parts)
                and parts[index + 1].strip().lower().strip(" >") == "name"
            )
            if name or has_delimited_name:
                if current is not None:
                    _append_dsml_call(calls, current, allowed)
                current = {"name": name, "args": {}}
                if has_delimited_name:
                    current["name"] = _clean_dsml_value(parts[index + 2])
                    index += 2
                if inline.strip() and current.get("name"):
                    # Some gateways put a single scalar argument directly
                    # after the invoke header. Keep it only as a fallback;
                    # normal calls use parameter blocks below.
                    current.setdefault("_inline", inline.strip())
            elif current is not None:
                _append_dsml_call(calls, current, allowed)
                current = None
            index += 1
            continue

        if lower.startswith("parameter") and current is not None:
            header, inline = _split_dsml_header(part, "parameter")
            attrs = _parse_dsml_attributes(header)
            parameter_name = str(attrs.get("name") or "").strip()
            if not parameter_name:
                # Marker-delimited form: parameter / name / key / string /
                # true / value. A bare parameter followed by invoke/tool_calls
                # is the closing marker and carries no value.
                next_lower = (
                    parts[index + 1].strip().lower().strip(" >")
                    if index + 1 < len(parts)
                    else ""
                )
                if next_lower == "name" and index + 2 < len(parts):
                    parameter_name = _clean_dsml_value(parts[index + 2])
                    value_index = index + 3
                    if (
                        value_index + 1 < len(parts)
                        and parts[value_index].strip().lower().strip(" >")
                        in {"string", "json", "number", "boolean", "object", "array"}
                        and parts[value_index + 1].strip().lower().strip(" >")
                        in {"true", "false"}
                    ):
                        value_index += 2
                    if value_index < len(parts):
                        current["args"][parameter_name] = _coerce_dsml_value(
                            _clean_dsml_value(parts[value_index]),
                            attrs,
                        )
                        index = value_index + 1
                        continue
                index += 1
                continue

            value = inline.strip()
            if not value and index + 1 < len(parts):
                candidate = parts[index + 1].strip()
                if candidate.lower().strip(" >") not in {
                    "parameter",
                    "invoke",
                    "tool_calls",
                    "function_calls",
                }:
                    value = candidate
                    index += 1
            if value:
                current["args"][parameter_name] = _coerce_dsml_value(value, attrs)
            index += 1
            continue

        # Marker-delimited invoke / name / tool_name form can be split across
        # individual DSML segments rather than attributes.
        if current is not None and not str(current.get("name") or "").strip():
            if lower == "name" and index + 1 < len(parts):
                current["name"] = _clean_dsml_value(parts[index + 1])
                index += 2
                continue
        index += 1

    if current is not None:
        _append_dsml_call(calls, current, allowed)
    return calls


def _split_dsml_header(part: str, keyword: str) -> tuple[str, str]:
    rendered = str(part or "").strip()
    match = re.match(rf"{re.escape(keyword)}\b(?P<rest>.*)", rendered, re.IGNORECASE | re.DOTALL)
    if not match:
        return rendered, ""
    rest = str(match.group("rest") or "").strip()
    if ">" not in rest:
        return rest, ""
    header, inline = rest.split(">", 1)
    return header.strip(), inline.strip()


def _parse_dsml_attributes(value: str) -> dict[str, str]:
    output: dict[str, str] = {}
    for match in _DSML_ATTRIBUTE_RE.finditer(str(value or "")):
        output[str(match.group("key") or "").strip().lower()] = str(
            match.group("double")
            or match.group("single")
            or match.group("bare")
            or ""
        )
    return output


def _clean_dsml_value(value: Any) -> str:
    rendered = html.unescape(str(value or "").strip())
    rendered = re.sub(
        r"</\s*(?:parameter|invoke|tool_calls|function_calls)\s*>$",
        "",
        rendered,
        flags=re.IGNORECASE,
    )
    return rendered.strip(" >")


def _coerce_dsml_value(value: Any, attrs: dict[str, str]) -> Any:
    rendered = _clean_dsml_value(value)
    declared_type = str(attrs.get("type") or "").strip().lower()
    if declared_type in {"json", "object", "array"} or (
        declared_type != "string" and rendered[:1] in {"{", "["}
    ):
        with_json = rendered
        try:
            return json.loads(with_json)
        except Exception:
            pass
    return rendered


def _append_dsml_call(
    calls: list[dict[str, Any]], current: dict[str, Any], allowed: set[str]
) -> None:
    name = str(current.get("name") or "").strip()
    if not name or (allowed and name not in allowed):
        return
    calls.append(
        {
            "name": name,
            "args": dict(current.get("args") or {}),
        }
    )


def looks_like_pending_action(user_text: str, assistant_text: str) -> bool:
    """Detect a final reply that promises an action without reporting a result.

    This is deliberately narrow: it requires both an actionable user request and
    a future/ongoing-action phrase in the assistant reply.  It is used as a
    runtime safety net when a tool-capable model ends its turn with a promise
    instead of invoking a tool.
    """

    request = str(user_text or "").strip()
    response = str(assistant_text or "").strip()
    if not request or not response:
        return False
    if not any(marker in request for marker in _ACTION_REQUEST_MARKERS):
        return False
    return any(pattern.search(response) for pattern in _PENDING_ACTION_RESPONSE_PATTERNS)


def sanitize_visible_assistant_text(text: str) -> str:
    """Remove obvious planning/reasoning prefixes from user-visible text."""

    payload = str(text or "")
    if not payload.strip():
        return ""

    stripped = payload.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        return payload

    lines = payload.splitlines()
    while len(lines) > 1 and _is_visible_thinking_line(lines[0]):
        lines.pop(0)
    return "\n".join(lines).strip() if lines else ""


def _is_visible_thinking_line(line: str) -> bool:
    rendered = str(line or "").strip()
    if not rendered:
        return True
    if _contains_cjk(rendered):
        return False
    return any(pattern.match(rendered) for pattern in _VISIBLE_THINKING_PREFIXES)


def _contains_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in str(text or ""))


def resolve_agents_model_config(
    *,
    model_key: str | None = None,
    provider: str | None = None,
) -> AgentsModelConfig:
    from core.model_config import (
        get_api_key_for_model,
        get_base_url_for_model,
        get_headers_for_model,
        get_model_id_for_api,
        get_models_config,
        select_model_for_role,
    )

    resolved_model_key = str(model_key or "").strip() or select_model_for_role(
        "primary"
    )
    model_id = get_model_id_for_api(resolved_model_key)
    api_key = os.getenv("OPENAI_API_KEY") or get_api_key_for_model(resolved_model_key)
    base_url = os.getenv("OPENAI_BASE_URL") or get_base_url_for_model(
        resolved_model_key
    )
    headers = get_headers_for_model(resolved_model_key)
    models_config = get_models_config()
    model_metadata = (
        models_config.get_model(resolved_model_key) if models_config else None
    )
    reasoning_enabled = bool(getattr(model_metadata, "reasoning", False))
    resolved_provider = str(
        provider or os.getenv("OPENAI_PROVIDER") or ""
    ).strip().lower() or _infer_provider(base_url)
    force_responses_model = (
        os.getenv("OPENAI_FORCE_RESPONSES_MODEL", "false").strip().lower() == "true"
    )
    tracing_disabled = (
        os.getenv("OPENAI_TRACING_DISABLED", "true").strip().lower() != "false"
    )
    return AgentsModelConfig(
        api_key=str(api_key or "").strip(),
        base_url=str(base_url or "").strip() or None,
        model=str(os.getenv("OPENAI_MODEL") or model_id or "").strip(),
        headers=headers,
        provider=resolved_provider,
        reasoning=reasoning_enabled,
        force_responses_model=force_responses_model,
        tracing_disabled=tracing_disabled,
    )


def _infer_provider(base_url: str | None) -> str:
    rendered = str(base_url or "").strip().lower()
    if not rendered or "api.openai.com" in rendered:
        return "openai"
    return "openai-compatible"


def build_agent_model(
    config: AgentsModelConfig,
    *,
    sdk: Any | None = None,
    client_factory: Callable[..., Any] | None = None,
) -> Any:
    """Build an Agents SDK model while keeping SDK imports lazy."""

    sdk_module = sdk or _load_agents_sdk()
    if bool(config.tracing_disabled):
        sdk_module.set_tracing_disabled(True)

    resolved_client_factory = client_factory or sdk_module.AsyncOpenAI
    client_kwargs: dict[str, Any] = {
        "api_key": config.api_key,
        "timeout": float(config.timeout),
    }
    if config.base_url:
        client_kwargs["base_url"] = config.base_url
    if config.headers:
        client_kwargs["default_headers"] = dict(config.headers)
    client = resolved_client_factory(**client_kwargs)

    provider = str(config.provider or "openai").strip().lower()
    official_openai_endpoint = provider == "openai" and (
        not str(config.base_url or "").strip()
        or "api.openai.com" in str(config.base_url or "").lower()
    )
    if not official_openai_endpoint and hasattr(client, "chat"):
        client = _ReasoningCompatibleClient(client)
    if provider == "openai" and bool(config.force_responses_model):
        return sdk_module.OpenAIResponsesModel(
            model=config.model,
            openai_client=client,
        )
    return sdk_module.OpenAIChatCompletionsModel(
        model=config.model,
        openai_client=client,
    )


class _ReasoningCompatibleClient:
    """Retry one incompatible tool-history request without replay metadata.

    Some OpenAI-compatible gateways enter thinking mode for a tool turn but do
    not return the provider's hidden reasoning field.  The next request then
    fails validation before the Agents SDK can produce a final answer.  When
    that specific error occurs, retain the visible tool results as user context
    and ask for a final response without another tool call.
    """

    def __init__(self, delegate: Any):
        self._delegate = delegate
        self.chat = SimpleNamespace(
            completions=_ReasoningCompatibleCompletions(delegate.chat.completions)
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)


class _ReasoningCompatibleCompletions:
    def __init__(self, delegate: Any):
        self._delegate = delegate

    async def create(self, **kwargs: Any) -> Any:
        try:
            response = await self._delegate.create(**kwargs)
            if kwargs.get("stream") and hasattr(response, "__aiter__"):
                return _ReasoningCompatibleStream(self, response, kwargs)
            return _normalize_reasoning_response(response)
        except Exception as exc:
            if not _is_reasoning_replay_error(exc):
                raise
            fallback_messages = _flatten_tool_history_for_retry(
                kwargs.get("messages")
            )
            if fallback_messages is None:
                raise
            logger.warning(
                "OpenAI-compatible gateway rejected reasoning history; retrying without provider replay metadata."
            )
            retry_kwargs = _strip_reasoning_retry_fields(kwargs)
            retry_kwargs["messages"] = fallback_messages
            retry_kwargs["tool_choice"] = "none"
            response = await self._delegate.create(**retry_kwargs)
            if retry_kwargs.get("stream") and hasattr(response, "__aiter__"):
                return _ReasoningCompatibleStream(self, response, retry_kwargs)
            return _normalize_reasoning_response(response)


class _ReasoningCompatibleStream:
    """Retry a streamed provider error after stripping invalid tool history."""

    def __init__(
        self,
        owner: _ReasoningCompatibleCompletions,
        delegate: Any,
        kwargs: dict[str, Any],
    ):
        self._owner = owner
        self._delegate = delegate
        self._kwargs = dict(kwargs)

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        reasoning_error: Exception | None = None
        try:
            async for chunk in self._delegate:
                yield _normalize_reasoning_chunk(chunk)
            return
        except Exception as exc:
            if not _is_reasoning_replay_error(exc):
                raise
            reasoning_error = exc

        fallback_messages = _flatten_tool_history_for_retry(
            self._kwargs.get("messages")
        )
        if fallback_messages is None:
            if reasoning_error is not None:
                raise reasoning_error
            return
        retry_kwargs = _strip_reasoning_retry_fields(self._kwargs)
        retry_kwargs["messages"] = fallback_messages
        retry_kwargs["tool_choice"] = "none"
        retry_stream = await self._owner._delegate.create(**retry_kwargs)
        async for chunk in retry_stream:
            yield _normalize_reasoning_chunk(chunk)


def _is_reasoning_replay_error(exc: Exception) -> bool:
    text = str(exc or "").lower()
    return "reasoning_content" in text and "thinking" in text


def _strip_reasoning_retry_fields(kwargs: dict[str, Any]) -> dict[str, Any]:
    retry_kwargs = dict(kwargs)
    for key in (
        "tools",
        "parallel_tool_calls",
        "response_format",
        "reasoning_effort",
    ):
        retry_kwargs.pop(key, None)
    extra_body = retry_kwargs.get("extra_body")
    if isinstance(extra_body, dict):
        cleaned_body = dict(extra_body)
        cleaned_body.pop("thinking", None)
        cleaned_body.pop("chat_template_kwargs", None)
        retry_kwargs["extra_body"] = cleaned_body or None
    return retry_kwargs


def _normalize_reasoning_response(response: Any) -> Any:
    """Expose provider-specific ``reasoning`` under the SDK's expected name."""

    choices = getattr(response, "choices", None)
    for choice in list(choices or []):
        message = getattr(choice, "message", None)
        if message is None or getattr(message, "reasoning_content", None):
            continue
        extra = getattr(message, "model_extra", None)
        if not isinstance(extra, dict):
            continue
        value = extra.get("reasoning_content")
        if value is None:
            value = extra.get("reasoning")
        if value is None:
            continue
        try:
            setattr(message, "reasoning_content", value)
        except Exception:
            # Pydantic models with strict extra handling may reject setattr;
            # the Agents SDK can still consume the original provider field.
            continue
    return response


def _normalize_reasoning_chunk(chunk: Any) -> Any:
    choices = getattr(chunk, "choices", None)
    for choice in list(choices or []):
        delta = getattr(choice, "delta", None)
        if delta is None or getattr(delta, "reasoning_content", None):
            continue
        extra = getattr(delta, "model_extra", None)
        if not isinstance(extra, dict):
            continue
        value = extra.get("reasoning_content")
        if value is None:
            value = extra.get("reasoning")
        if value is None:
            continue
        try:
            setattr(delta, "reasoning_content", value)
        except Exception:
            continue
    return chunk


def _flatten_tool_history_for_retry(messages: Any) -> list[dict[str, Any]] | None:
    if not isinstance(messages, list):
        return None

    flattened: list[dict[str, Any]] = []
    tool_results: list[str] = []
    saw_tool_message = False
    saw_reasoning_metadata = False
    for item in messages:
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "").strip().lower() == "reasoning":
            saw_reasoning_metadata = True
            continue
        role = str(item.get("role") or "").strip().lower()
        if role == "assistant" and item.get("tool_calls"):
            saw_tool_message = True
            continue
        if role == "tool":
            saw_tool_message = True
            tool_id = str(item.get("tool_call_id") or "").strip()
            content = str(item.get("content") or "").strip()
            prefix = f"工具结果{f'（{tool_id}）' if tool_id else ''}"
            tool_results.append(f"{prefix}：{content}".strip("："))
            continue
        copied = dict(item)
        if role == "assistant":
            if "reasoning_content" in copied or "reasoning" in copied:
                saw_reasoning_metadata = True
            copied.pop("reasoning_content", None)
            copied.pop("reasoning", None)
        flattened.append(copied)

    if not saw_tool_message and not saw_reasoning_metadata:
        return None
    if tool_results:
        flattened.append(
            {
                "role": "user",
                "content": (
                    "系统提示：前面的工具已经执行完毕。以下是工具结果，请直接基于结果回复用户，"
                    "不要再次调用工具。\n" + "\n".join(tool_results)
                ),
            }
        )
    return flattened


def _load_agents_sdk() -> Any:
    try:
        from agents import (  # type: ignore[import-not-found]
            OpenAIChatCompletionsModel,
            OpenAIResponsesModel,
            set_tracing_disabled,
        )
        from openai import AsyncOpenAI
    except Exception as exc:  # pragma: no cover - exercised through runtime error
        raise RuntimeError(
            "OpenAI Agents SDK is unavailable. Install the `openai-agents` dependency."
        ) from exc

    return SimpleNamespace(
        AsyncOpenAI=AsyncOpenAI,
        OpenAIChatCompletionsModel=OpenAIChatCompletionsModel,
        OpenAIResponsesModel=OpenAIResponsesModel,
        set_tracing_disabled=set_tracing_disabled,
    )
