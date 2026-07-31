from __future__ import annotations

from types import SimpleNamespace

import pytest

from api.schemas.admin_config import ModelsLatencyCheckRequest
from api.services import admin_config_service
from core import config as config_module
from core import model_config as model_config_module
from core.agents.runtime import AgentsModelConfig, build_agent_model


def test_parse_models_config_loads_provider_headers():
    config = model_config_module._parse_models_config_data(
        {
            "providers": {
                "proxy": {
                    "baseUrl": "https://example.invalid/v1",
                    "apiKey": "test-key",
                    "headers": {
                        "opencodex-api-key": "custom-key",
                        "X-Tenant": "tenant-1",
                    },
                    "models": [{"id": "model-1"}],
                }
            }
        }
    )

    assert config.providers["proxy"].headers == {
        "opencodex-api-key": "custom-key",
        "X-Tenant": "tenant-1",
    }


def test_openai_client_receives_provider_headers(monkeypatch):
    captured: dict[str, object] = {}

    class _FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(config_module, "AsyncOpenAI", _FakeAsyncOpenAI)
    monkeypatch.setattr(config_module, "OpenAI", _FakeAsyncOpenAI)
    monkeypatch.setattr(
        model_config_module,
        "get_api_key_for_model",
        lambda _key: "test-key",
    )
    monkeypatch.setattr(
        model_config_module,
        "get_base_url_for_model",
        lambda _key: "https://example.invalid/v1",
    )
    monkeypatch.setattr(
        model_config_module,
        "get_headers_for_model",
        lambda _key: {"opencodex-api-key": "custom-key"},
    )
    monkeypatch.setattr(
        "core.llm_usage_store.wrap_openai_client",
        lambda client, **_kwargs: client,
    )
    config_module._clients_cache.clear()
    config_module._wrapped_clients_cache.clear()

    config_module.get_client_for_model("proxy/model-1", is_async=True)

    assert captured["default_headers"] == {
        "opencodex-api-key": "custom-key"
    }


def test_openai_client_can_suppress_bearer_auth(monkeypatch):
    captured: dict[str, object] = {}

    class _FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(config_module, "AsyncOpenAI", _FakeOpenAI)
    monkeypatch.setattr(config_module, "OpenAI", _FakeOpenAI)
    monkeypatch.setattr(
        model_config_module,
        "get_api_key_for_model",
        lambda _key: "test-key",
    )
    monkeypatch.setattr(
        model_config_module,
        "get_base_url_for_model",
        lambda _key: "https://example.invalid/v1",
    )
    monkeypatch.setattr(
        model_config_module,
        "get_headers_for_model",
        lambda _key: {
            "authorization": "Bearer provider-token",
            "X-Tenant": "tenant-1",
        },
    )
    monkeypatch.setattr(
        "core.llm_usage_store.wrap_openai_client",
        lambda client, **_kwargs: client,
    )
    config_module._clients_cache.clear()
    config_module._wrapped_clients_cache.clear()

    config_module.get_client_for_model(
        "proxy/model-1",
        is_async=False,
        suppress_bearer_auth=True,
    )

    assert captured["default_headers"] == {
        "X-Tenant": "tenant-1",
        "Authorization": "",
    }


def test_agents_sdk_client_receives_provider_headers():
    captured: dict[str, object] = {}

    class _FakeSdk:
        @staticmethod
        def set_tracing_disabled(_value):
            return None

        @staticmethod
        def OpenAIChatCompletionsModel(*, model, openai_client):
            return SimpleNamespace(model=model, openai_client=openai_client)

    build_agent_model(
        AgentsModelConfig(
            api_key="test-key",
            base_url="https://example.invalid/v1",
            model="model-1",
            headers={"opencodex-api-key": "custom-key"},
        ),
        sdk=_FakeSdk,
        client_factory=lambda **kwargs: captured.update(kwargs) or object(),
    )

    assert captured["default_headers"] == {
        "opencodex-api-key": "custom-key"
    }


@pytest.mark.asyncio
async def test_models_latency_check_sends_custom_headers(monkeypatch):
    captured: dict[str, object] = {}

    class _FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    async def _fake_create_chat_completion(**_kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="pong"))]
        )

    monkeypatch.setattr(admin_config_service, "AsyncOpenAI", _FakeAsyncOpenAI)
    monkeypatch.setattr(
        admin_config_service,
        "create_chat_completion",
        _fake_create_chat_completion,
    )

    await admin_config_service.run_models_latency_check(
        ModelsLatencyCheckRequest(
            role="routing",
            provider_name="proxy",
            base_url="https://example.invalid/v1",
            api_key="test-key",
            headers={"opencodex-api-key": "custom-key"},
            model_id="model-1",
        )
    )

    assert captured["default_headers"] == {
        "opencodex-api-key": "custom-key"
    }
