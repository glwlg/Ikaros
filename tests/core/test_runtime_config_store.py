import json

from core.runtime_config_store import RuntimeConfigStore


def test_routing_model_feature_defaults_to_enabled(tmp_path):
    store = RuntimeConfigStore()
    store.path = (tmp_path / "runtime-config.json").resolve()

    assert store.is_feature_enabled("routing_model_enabled") is True


def test_routing_model_feature_can_be_disabled(tmp_path):
    store = RuntimeConfigStore()
    store.path = (tmp_path / "runtime-config.json").resolve()
    store.path.write_text(
        json.dumps({"features": {"routing_model_enabled": False}}),
        encoding="utf-8",
    )

    assert store.is_feature_enabled("routing_model_enabled", default=True) is False
