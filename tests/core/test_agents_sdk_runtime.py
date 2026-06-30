from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.agents import AgentsSdkAssistantRuntime
from core.agents.runtime import (
    AgentsModelConfig,
    build_agent_model,
    looks_like_unexecuted_tool_call,
    sanitize_visible_assistant_text,
)
from core.agents.tools import build_agent_tools
from core.agent_orchestrator import AgentOrchestrator
from services.ai_service import AiService


class _FakeChatCompletionsModel:
    def __init__(self, *, model, openai_client):
        self.model = model
        self.openai_client = openai_client


class _FakeResponsesModel:
    def __init__(self, *, model, openai_client):
        self.model = model
        self.openai_client = openai_client


class _FakeModelSdk:
    OpenAIChatCompletionsModel = _FakeChatCompletionsModel
    OpenAIResponsesModel = _FakeResponsesModel
    tracing_disabled = False

    @staticmethod
    def set_tracing_disabled(value):
        _FakeModelSdk.tracing_disabled = bool(value)


def test_agents_model_defaults_openai_compatible_to_chat_completions():
    captured_client_kwargs = {}

    def fake_client_factory(**kwargs):
        captured_client_kwargs.update(kwargs)
        return SimpleNamespace(kind="client")

    model = build_agent_model(
        AgentsModelConfig(
            api_key="key",
            base_url="http://litellm.example/v1",
            model="glm-5.1",
            provider="openai-compatible",
            force_responses_model=True,
        ),
        sdk=_FakeModelSdk,
        client_factory=fake_client_factory,
    )

    assert isinstance(model, _FakeChatCompletionsModel)
    assert model.model == "glm-5.1"
    assert captured_client_kwargs["base_url"] == "http://litellm.example/v1"
    assert _FakeModelSdk.tracing_disabled is True


def test_agents_model_uses_responses_only_for_official_openai_when_forced():
    model = build_agent_model(
        AgentsModelConfig(
            api_key="key",
            base_url=None,
            model="gpt-5.4",
            provider="openai",
            force_responses_model=True,
        ),
        sdk=_FakeModelSdk,
        client_factory=lambda **_kwargs: SimpleNamespace(kind="client"),
    )

    assert isinstance(model, _FakeResponsesModel)


def test_agents_model_loads_real_sdk_without_class_scope_regression():
    model = build_agent_model(
        AgentsModelConfig(
            api_key="test",
            base_url="http://example.com/v1",
            model="test-model",
            provider="openai-compatible",
        )
    )

    assert type(model).__name__ == "OpenAIChatCompletionsModel"
    assert getattr(model, "model", None) == "test-model"


def test_orchestrator_keeps_native_runtime_by_default(monkeypatch):
    monkeypatch.setenv("IKAROS_KERNEL", "native")
    orchestrator = AgentOrchestrator()

    assert isinstance(orchestrator._select_assistant_runtime(), AiService)


def test_orchestrator_selects_agents_sdk_runtime_when_enabled(monkeypatch):
    monkeypatch.setenv("IKAROS_KERNEL", "agents_sdk")
    orchestrator = AgentOrchestrator()

    assert isinstance(orchestrator._select_assistant_runtime(), AgentsSdkAssistantRuntime)


class _FakeFunctionTool:
    def __init__(self, **kwargs):
        self.name = kwargs["name"]
        self.description = kwargs["description"]
        self.params_json_schema = kwargs["params_json_schema"]
        self.on_invoke_tool = kwargs["on_invoke_tool"]
        self.strict_json_schema = kwargs["strict_json_schema"]


@pytest.mark.asyncio
async def test_build_agent_tools_invokes_business_tool_and_serializes_result():
    events = []

    async def executor(name, args):
        assert name == "lookup"
        assert args == {"query": None, "limit": 3}
        return {"ok": True, "result": "done"}

    async def event_callback(event, payload):
        events.append((event, payload))

    tools = build_agent_tools(
        tools=[
            {
                "name": "lookup",
                "description": "Lookup data",
                "parameters": {"type": "object", "properties": {}},
            }
        ],
        tool_executor=executor,
        event_callback=event_callback,
        sdk=SimpleNamespace(FunctionTool=_FakeFunctionTool),
    )

    payload = await tools[0].on_invoke_tool(None, '{"query":"","limit":3}')

    assert '"result": "done"' in payload
    assert [event for event, _payload in events] == [
        "tool_call_started",
        "tool_call_finished",
    ]
    assert events[-1][1]["ok"] is True


@pytest.mark.asyncio
async def test_build_agent_tools_returns_structured_error_for_invalid_args():
    events = []

    async def executor(_name, _args):
        raise AssertionError("executor should not run for invalid JSON")

    tools = build_agent_tools(
        tools=[{"name": "lookup", "description": "", "parameters": {}}],
        tool_executor=executor,
        event_callback=lambda event, payload: events.append((event, payload)),
        sdk=SimpleNamespace(FunctionTool=_FakeFunctionTool),
    )

    payload = await tools[0].on_invoke_tool(None, "[1, 2]")

    assert "invalid_json_args" in payload
    assert [event for event, _payload in events] == [
        "tool_call_started",
        "tool_call_finished",
    ]
    assert events[-1][1]["ok"] is False


def test_build_agent_tools_loads_real_sdk_without_class_scope_regression():
    tools = build_agent_tools(
        tools=[{"name": "lookup", "description": "", "parameters": {}}],
        tool_executor=lambda _name, _args: {"ok": True},
    )

    assert len(tools) == 1
    assert type(tools[0]).__name__ == "FunctionTool"


def test_agents_runtime_sanitizers_hide_reasoning_and_unexecuted_tool_calls():
    assert looks_like_unexecuted_tool_call('<tool_call>{"name":"x"}</tool_call>')
    assert looks_like_unexecuted_tool_call('{"tool_calls":[]}')
    assert (
        sanitize_visible_assistant_text("The user asks for data.\n这里是正式回复")
        == "这里是正式回复"
    )
    assert sanitize_visible_assistant_text('{"ok":true}') == '{"ok":true}'


class _FakeAgent:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _FakeModelSettings:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _FakeStreamingResult:
    def __init__(self, *, events, final_output):
        self._events = events
        self.final_output = final_output

    async def stream_events(self):
        for event in self._events:
            yield event


class _FakeRunner:
    captured = {}
    result = None

    @classmethod
    def run_streamed(cls, agent, *, input, max_turns):
        cls.captured = {
            "agent": agent,
            "input": input,
            "max_turns": max_turns,
        }
        return cls.result


def _raw_event(event_type: str, delta: str):
    return SimpleNamespace(
        type="raw_response_event",
        data=SimpleNamespace(type=event_type, delta=delta),
    )


@pytest.mark.asyncio
async def test_assistant_runtime_only_streams_output_text_delta(monkeypatch):
    _FakeRunner.result = _FakeStreamingResult(
        events=[
            _raw_event("response.reasoning_text.delta", "secret plan"),
            _raw_event("response.output_text.delta", "你好"),
        ],
        final_output="你好",
    )
    events = []
    runtime = AgentsSdkAssistantRuntime(
        runner=_FakeRunner,
        agent_cls=_FakeAgent,
        model_settings_cls=_FakeModelSettings,
        model_builder=lambda _config: "model",
    )
    monkeypatch.setattr(
        "core.agents.assistant.resolve_agents_model_config",
        lambda: AgentsModelConfig(api_key="key", base_url=None, model="gpt-5.4"),
    )

    chunks = [
        chunk
        async for chunk in runtime.generate_response_stream(
            [{"role": "user", "parts": [{"text": "hi"}]}],
            event_callback=lambda event, payload: events.append((event, payload)),
        )
    ]

    assert chunks == ["你好"]
    assert _FakeRunner.captured["input"] == [{"role": "user", "content": "hi"}]
    assert events[-1][0] == "final_response"
    assert "secret" not in events[-1][1]["text"]


@pytest.mark.asyncio
async def test_assistant_runtime_blocks_unexecuted_final_tool_call(monkeypatch):
    _FakeRunner.result = _FakeStreamingResult(
        events=[], final_output="<tool_call>{}</tool_call>"
    )
    events = []
    runtime = AgentsSdkAssistantRuntime(
        runner=_FakeRunner,
        agent_cls=_FakeAgent,
        model_settings_cls=_FakeModelSettings,
        model_builder=lambda _config: "model",
    )
    monkeypatch.setattr(
        "core.agents.assistant.resolve_agents_model_config",
        lambda: AgentsModelConfig(api_key="key", base_url=None, model="gpt-5.4"),
    )

    chunks = [
        chunk
        async for chunk in runtime.generate_response_stream(
            [{"role": "user", "parts": [{"text": "hi"}]}],
            event_callback=lambda event, payload: events.append((event, payload)),
        )
    ]

    assert chunks == ["⚠️ 模型返回了未执行的工具调用，已拦截。"]
    assert events[-1][0] == "final_response"
    assert events[-1][1]["completion_signal"]["status"] == "failed"
