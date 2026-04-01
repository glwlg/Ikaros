import importlib
from pathlib import Path


def test_api_core_config_defaults_to_runtime_home_paths(tmp_path, monkeypatch):
    import api.core.config as api_config

    ikaros_home = tmp_path / ".ikaros"
    with monkeypatch.context() as scoped:
        for name in (
            "IKAROS_HOME",
            "DATA_DIR",
            "MODELS_CONFIG_PATH",
            "MEMORY_CONFIG_PATH",
            "X_DEPLOYMENT_TARGETS_FILE",
        ):
            scoped.delenv(name, raising=False)
        scoped.setenv("IKAROS_HOME", str(ikaros_home))

        reloaded = importlib.reload(api_config)

        assert Path(reloaded.settings.sqlite.database) == (
            ikaros_home / "data" / "bot_data.db"
        ).resolve()
        assert reloaded.AppConfig.model_config.get("env_file") == str(
            reloaded.env_path()
        )

    importlib.reload(api_config)
