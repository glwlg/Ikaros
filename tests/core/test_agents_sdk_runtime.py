from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.agents import AgentsSdkAssistantRuntime, to_agents_sdk_input
from core.agents.runtime import (
    AgentsModelConfig,
    _ReasoningCompatibleCompletions,
    build_agent_model,
    looks_like_unexecuted_tool_call,
    looks_like_pending_action,
    parse_legacy_dsml_tool_calls,
    sanitize_visible_assistant_text,
)
from core.agents.tools import build_agent_tools
from core.agent_orchestrator import AgentOrchestrator
from services.openai_adapter import (
    build_chat_completion_from_stream_chunks,
    build_messages,
)


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


def test_agents_model_wraps_proxy_even_when_provider_label_is_openai():
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace()))
    model = build_agent_model(
        AgentsModelConfig(
            api_key="key",
            base_url="http://proxy.example/v1",
            model="deepseek-v4",
            provider="openai",
        ),
        sdk=_FakeModelSdk,
        client_factory=lambda **_kwargs: client,
    )

    assert type(model.openai_client).__name__ == "_ReasoningCompatibleClient"


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


def test_orchestrator_uses_agents_sdk_by_default(monkeypatch):
    monkeypatch.delenv("IKAROS_KERNEL", raising=False)
    orchestrator = AgentOrchestrator()

    assert isinstance(
        orchestrator._select_assistant_runtime(), AgentsSdkAssistantRuntime
    )


def test_removed_native_kernel_alias_uses_agents_sdk(monkeypatch):
    monkeypatch.setenv("IKAROS_KERNEL", "native")
    orchestrator = AgentOrchestrator()

    assert isinstance(
        orchestrator._select_assistant_runtime(), AgentsSdkAssistantRuntime
    )


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
async def test_build_agent_tools_propagates_intermediate_delivery_data():
    events = []

    async def executor(_name, _args):
        return {
            "ok": True,
            "text": "✅ 中间消息已发送。",
            "data": {
                "text_sent": False,
                "delivered_files": [{"path": "/tmp/clip.mp4", "kind": "video"}],
            },
        }

    tools = build_agent_tools(
        tools=[{"name": "send_message", "description": "", "parameters": {}}],
        tool_executor=executor,
        event_callback=lambda event, payload: events.append((event, payload)),
        sdk=SimpleNamespace(FunctionTool=_FakeFunctionTool),
    )

    await tools[0].on_invoke_tool(None, "{}")

    assert events[-1][0] == "tool_call_finished"
    assert events[-1][1]["data"]["delivered_files"][0]["path"] == "/tmp/clip.mp4"


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
    assert looks_like_pending_action(
        "把这个帖子里的图片发给我",
        "我先看看这个帖子的内容，然后帮你把图片取下来。",
    )
    assert not looks_like_pending_action("你好吗", "我先看看天气。")


def test_parse_legacy_dsml_xml_tool_call():
    text = (
        '<|DSML|>tool_calls><|DSML|>invoke name="bash">'
        '<|DSML|>parameter name="command" string="true">echo hello'
        "<|DSML|>parameter><|DSML|>invoke><|DSML|>tool_calls>"
    )

    assert parse_legacy_dsml_tool_calls(text, allowed_tool_names={"bash"}) == [
        {"name": "bash", "args": {"command": "echo hello"}}
    ]


def test_parse_legacy_dsml_marker_delimited_tool_call():
    text = (
        "<｜DSML｜>function_calls<｜DSML｜>invoke<｜DSML｜>name<｜DSML｜>bash"
        "<｜DSML｜>parameter<｜DSML｜>name<｜DSML｜>command"
        "<｜DSML｜>string<｜DSML｜>true<｜DSML｜>echo hello"
        "<｜DSML｜>parameter<｜DSML｜>invoke<｜DSML｜>function_calls"
    )

    assert parse_legacy_dsml_tool_calls(text, allowed_tool_names={"bash"}) == [
        {"name": "bash", "args": {"command": "echo hello"}}
    ]


def test_stream_collection_preserves_reasoning_content():
    chunks = [
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason=None,
                    delta=SimpleNamespace(
                        content=None,
                        reasoning_content="internal reasoning",
                        tool_calls=[],
                        refusal=None,
                    ),
                )
            ]
        )
    ]

    response = build_chat_completion_from_stream_chunks(chunks)

    assert response.choices[0].message.reasoning_content == "internal reasoning"


@pytest.mark.asyncio
async def test_reasoning_gateway_retry_flattens_tool_history():
    class _FailingCompletions:
        calls = []

        async def create(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                raise RuntimeError(
                    "Upstream request failed: reasoning_content in thinking mode"
                )
            return "final"

    delegate = _FailingCompletions()
    completions = _ReasoningCompatibleCompletions(delegate)
    result = await completions.create(
        messages=[
            {"role": "user", "content": "执行任务"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "call-1"}],
            },
            {"role": "tool", "tool_call_id": "call-1", "content": "完成"},
        ],
        tool_choice="auto",
    )

    assert result == "final"
    assert delegate.calls[1]["tool_choice"] == "auto"
    assert delegate.calls[1]["messages"][-1]["role"] == "user"
    assert "完成" in delegate.calls[1]["messages"][-1]["content"]
    assert (
        "如仍需执行动作，请调用当前可用工具"
        in delegate.calls[1]["messages"][-1]["content"]
    )


@pytest.mark.asyncio
async def test_reasoning_gateway_retry_handles_stream_iteration_error():
    class _ErrorStream:
        def __aiter__(self):
            return self._iterate()

        async def _iterate(self):
            raise RuntimeError(
                "Provider error: reasoning_content in the thinking mode must be passed back"
            )
            yield None

    class _FinalStream:
        def __aiter__(self):
            return self._iterate()

        async def _iterate(self):
            yield "final"

    class _StreamingCompletions:
        def __init__(self):
            self.calls = []

        async def create(self, **kwargs):
            self.calls.append(kwargs)
            return _ErrorStream() if len(self.calls) == 1 else _FinalStream()

    delegate = _StreamingCompletions()
    completions = _ReasoningCompatibleCompletions(delegate)
    stream = await completions.create(
        stream=True,
        messages=[
            {"role": "user", "content": "执行任务"},
            {"role": "assistant", "tool_calls": [{"id": "call-1"}]},
            {"role": "tool", "tool_call_id": "call-1", "content": "完成"},
        ],
        tools=[{"type": "function"}],
        tool_choice="auto",
    )

    chunks = [chunk async for chunk in stream]

    assert chunks == ["final"]
    assert delegate.calls[1]["tool_choice"] == "auto"
    assert delegate.calls[1]["tools"] == [{"type": "function"}]


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


def test_to_agents_sdk_input_maps_chat_completions_image_parts():
    messages = build_messages(
        contents=[
            {
                "role": "user",
                "parts": [
                    {"text": "请分析这张图片"},
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": "abc123",
                        }
                    },
                ],
            }
        ]
    )

    converted = to_agents_sdk_input(messages)

    assert converted == [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "请分析这张图片"},
                {
                    "type": "input_image",
                    "image_url": "data:image/jpeg;base64,abc123",
                    "detail": "auto",
                },
            ],
        }
    ]


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
        lambda: AgentsModelConfig(
            api_key="key",
            base_url="http://proxy.example/v1",
            model="gpt-5.4",
            provider="openai-compatible",
        ),
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
    settings = _FakeRunner.captured["agent"].kwargs["model_settings"]
    assert settings.kwargs["extra_body"]["chat_template_kwargs"] == {
        "enable_thinking": False
    }
    assert settings.kwargs["extra_body"]["thinking"] == {"type": "disabled"}
    assert events[-1][0] == "final_response"
    assert "secret" not in events[-1][1]["text"]


@pytest.mark.asyncio
async def test_assistant_runtime_sends_configured_reasoning_effort(monkeypatch):
    _FakeRunner.result = _FakeStreamingResult(events=[], final_output="ok")
    runtime = AgentsSdkAssistantRuntime(
        runner=_FakeRunner,
        agent_cls=_FakeAgent,
        model_settings_cls=_FakeModelSettings,
        model_builder=lambda _config: "model",
    )
    monkeypatch.setattr(
        "core.agents.assistant.resolve_agents_model_config",
        lambda: AgentsModelConfig(
            api_key="key",
            base_url="http://proxy.example/v1",
            model="gpt-5.6-terra",
            provider="openai-compatible",
            reasoning=True,
            reasoning_effort="xhigh",
        ),
    )

    chunks = [
        chunk
        async for chunk in runtime.generate_response_stream(
            [{"role": "user", "parts": [{"text": "hi"}]}]
        )
    ]

    assert chunks == ["ok"]
    settings = _FakeRunner.captured["agent"].kwargs["model_settings"]
    assert settings.kwargs["extra_body"]["reasoning_effort"] == "xhigh"
    assert "thinking" not in settings.kwargs["extra_body"]


@pytest.mark.asyncio
async def test_assistant_runtime_skips_reasoning_effort_when_reasoning_disabled(
    monkeypatch,
):
    _FakeRunner.result = _FakeStreamingResult(events=[], final_output="ok")
    runtime = AgentsSdkAssistantRuntime(
        runner=_FakeRunner,
        agent_cls=_FakeAgent,
        model_settings_cls=_FakeModelSettings,
        model_builder=lambda _config: "model",
    )
    monkeypatch.setattr(
        "core.agents.assistant.resolve_agents_model_config",
        lambda: AgentsModelConfig(
            api_key="key",
            base_url="http://proxy.example/v1",
            model="deepseek-v4-flash",
            provider="openai-compatible",
            reasoning=False,
            reasoning_effort="low",
        ),
    )

    chunks = [
        chunk
        async for chunk in runtime.generate_response_stream(
            [{"role": "user", "parts": [{"text": "hi"}]}]
        )
    ]

    assert chunks == ["ok"]
    settings = _FakeRunner.captured["agent"].kwargs["model_settings"]
    assert "reasoning_effort" not in settings.kwargs["extra_body"]
    assert settings.kwargs["extra_body"]["thinking"] == {"type": "disabled"}


@pytest.mark.asyncio
async def test_assistant_runtime_retries_action_promise_before_delivery(monkeypatch):
    class _QueueRunner:
        results = [
            _FakeStreamingResult(
                events=[],
                final_output="我先看看这个帖子的内容，然后帮你把图片取下来。",
            ),
            _FakeStreamingResult(events=[], final_output="图片已经准备好了。"),
        ]
        inputs = []

        @classmethod
        def run_streamed(cls, agent, *, input, max_turns):
            cls.inputs.append(input)
            del agent, max_turns
            return cls.results.pop(0)

    runtime = AgentsSdkAssistantRuntime(
        runner=_QueueRunner,
        agent_cls=_FakeAgent,
        model_settings_cls=_FakeModelSettings,
        model_builder=lambda _config: "model",
    )
    monkeypatch.setattr(
        "core.agents.assistant.resolve_agents_model_config",
        lambda: AgentsModelConfig(
            api_key="key",
            base_url="http://proxy.example/v1",
            model="deepseek-v4",
            provider="openai-compatible",
        ),
    )

    chunks = [
        chunk
        async for chunk in runtime.generate_response_stream(
            [
                {
                    "role": "user",
                    "parts": [{"text": "把这个帖子里的图片发给我"}],
                }
            ],
            tools=[
                {
                    "name": "download",
                    "description": "下载图片",
                    "parameters": {"type": "object", "properties": {}},
                }
            ],
            tool_executor=lambda _name, _args: {"ok": True},
        )
    ]

    assert chunks == ["图片已经准备好了。"]
    assert len(_QueueRunner.inputs) == 2
    assert "必须立即调用" in _QueueRunner.inputs[1][-1]["content"]


@pytest.mark.asyncio
async def test_assistant_runtime_executes_legacy_dsml_tool_call(monkeypatch):
    class _QueueRunner:
        results = [
            _FakeStreamingResult(
                events=[],
                final_output=(
                    '<|DSML|>tool_calls><|DSML|>invoke name="bash">'
                    '<|DSML|>parameter name="command" string="true">echo hello'
                    "<|DSML|>parameter><|DSML|>invoke><|DSML|>tool_calls>"
                ),
            ),
            _FakeStreamingResult(events=[], final_output="工具已执行：hello"),
        ]
        inputs = []

        @classmethod
        def run_streamed(cls, agent, *, input, max_turns):
            cls.inputs.append(input)
            del agent, max_turns
            return cls.results.pop(0)

    executed = []
    events = []

    async def executor(name, args):
        executed.append((name, args))
        return {"ok": True, "text": "hello"}

    runtime = AgentsSdkAssistantRuntime(
        runner=_QueueRunner,
        agent_cls=_FakeAgent,
        model_settings_cls=_FakeModelSettings,
        model_builder=lambda _config: "model",
    )
    monkeypatch.setattr(
        "core.agents.assistant.resolve_agents_model_config",
        lambda: AgentsModelConfig(
            api_key="key",
            base_url="http://proxy.example/v1",
            model="deepseek-v4",
            provider="openai-compatible",
        ),
    )

    chunks = [
        chunk
        async for chunk in runtime.generate_response_stream(
            [{"role": "user", "parts": [{"text": "执行命令"}]}],
            tools=[
                {
                    "name": "bash",
                    "description": "运行命令",
                    "parameters": {
                        "type": "object",
                        "properties": {"command": {"type": "string"}},
                        "required": ["command"],
                    },
                }
            ],
            tool_executor=executor,
            event_callback=lambda event, payload: events.append((event, payload)),
        )
    ]

    assert chunks == ["工具已执行：hello"]
    assert executed == [("bash", {"command": "echo hello"})]
    assert [event for event, _payload in events].count("tool_call_started") == 1
    assert [event for event, _payload in events].count("tool_call_finished") == 1


@pytest.mark.asyncio
async def test_assistant_runtime_converts_image_parts_for_agents_sdk(monkeypatch):
    _FakeRunner.result = _FakeStreamingResult(events=[], final_output="ok")
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
            [
                {
                    "role": "user",
                    "parts": [
                        {"text": "请分析这张图片"},
                        {
                            "inline_data": {
                                "mime_type": "image/jpeg",
                                "data": "abc123",
                            }
                        },
                    ],
                }
            ]
        )
    ]

    assert chunks == ["ok"]
    assert _FakeRunner.captured["input"] == [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "请分析这张图片"},
                {
                    "type": "input_image",
                    "image_url": "data:image/jpeg;base64,abc123",
                    "detail": "auto",
                },
            ],
        }
    ]


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
