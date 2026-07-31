from __future__ import annotations

import os
import re
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Callable


@dataclass(frozen=True)
class AgentsModelConfig:
    """Resolved model settings for the Agents SDK bridge."""

    api_key: str
    base_url: str | None
    model: str
    provider: str = "openai"
    force_responses_model: bool = False
    tracing_disabled: bool = True
    timeout: float = 600.0
    headers: dict[str, str] | None = None


_UNEXECUTED_TOOL_PATTERNS = [
    re.compile(r"<\s*/?\s*tool_call\b", re.IGNORECASE),
    re.compile(r'"tool_calls"\s*:', re.IGNORECASE),
    re.compile(r'"function_call"\s*:', re.IGNORECASE),
    re.compile(r"\btool_calls\s*=\s*\[", re.IGNORECASE),
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


def looks_like_unexecuted_tool_call(text: str) -> bool:
    payload = str(text or "")
    if not payload.strip():
        return False
    return any(pattern.search(payload) for pattern in _UNEXECUTED_TOOL_PATTERNS)


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
    if provider == "openai" and bool(config.force_responses_model):
        return sdk_module.OpenAIResponsesModel(
            model=config.model,
            openai_client=client,
        )
    return sdk_module.OpenAIChatCompletionsModel(
        model=config.model,
        openai_client=client,
    )


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
