from pathlib import Path

from core import app_paths


def _clear_runtime_path_env(monkeypatch) -> None:
    for name in (
        "IKAROS_HOME",
        "DATA_DIR",
        "MODELS_CONFIG_PATH",
        "MEMORY_CONFIG_PATH",
        "X_DEPLOYMENT_TARGETS_FILE",
    ):
        monkeypatch.delenv(name, raising=False)


def test_env_path_is_pinned_to_project_root(monkeypatch, tmp_path):
    _clear_runtime_path_env(monkeypatch)
    monkeypatch.chdir(tmp_path)

    assert app_paths.env_path() == (app_paths.project_root() / ".env").resolve()


def test_app_paths_default_to_home_layout(monkeypatch, tmp_path):
    _clear_runtime_path_env(monkeypatch)
    monkeypatch.setattr(app_paths.Path, "home", lambda: tmp_path)

    assert app_paths.app_home() == (tmp_path / ".ikaros").resolve()
    assert app_paths.data_dir() == (tmp_path / ".ikaros" / "data").resolve()
    assert app_paths.config_dir() == (tmp_path / ".ikaros" / "config").resolve()
    assert app_paths.models_config_path() == (
        tmp_path / ".ikaros" / "config" / "models.json"
    ).resolve()
    assert app_paths.memory_config_path() == (
        tmp_path / ".ikaros" / "config" / "memory.json"
    ).resolve()
    assert app_paths.deployment_targets_path() == (
        tmp_path / ".ikaros" / "config" / "deployment_targets.yaml"
    ).resolve()


def test_app_paths_follow_ikaros_home(monkeypatch):
    _clear_runtime_path_env(monkeypatch)
    monkeypatch.setenv("IKAROS_HOME", "runtime-root")

    expected_home = (app_paths.project_root() / "runtime-root").resolve()
    assert app_paths.app_home() == expected_home
    assert app_paths.data_dir() == (expected_home / "data").resolve()
    assert app_paths.config_dir() == (expected_home / "config").resolve()


def test_explicit_runtime_path_env_vars_override_defaults(monkeypatch):
    _clear_runtime_path_env(monkeypatch)
    monkeypatch.setenv("IKAROS_HOME", "ignored-home")
    monkeypatch.setenv("DATA_DIR", "runtime-data")
    monkeypatch.setenv("MODELS_CONFIG_PATH", "runtime-config/models.json")
    monkeypatch.setenv("MEMORY_CONFIG_PATH", "runtime-config/memory.json")
    monkeypatch.setenv(
        "X_DEPLOYMENT_TARGETS_FILE", "runtime-config/deployment_targets.yaml"
    )

    repo_root = app_paths.project_root()
    assert app_paths.data_dir() == (repo_root / "runtime-data").resolve()
    assert app_paths.models_config_path() == (
        repo_root / "runtime-config" / "models.json"
    ).resolve()
    assert app_paths.memory_config_path() == (
        repo_root / "runtime-config" / "memory.json"
    ).resolve()
    assert app_paths.deployment_targets_path() == (
        repo_root / "runtime-config" / "deployment_targets.yaml"
    ).resolve()


def test_tilde_runtime_path_env_vars_expand_from_home(monkeypatch, tmp_path):
    _clear_runtime_path_env(monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("DATA_DIR", "~/.ikaros/data")
    monkeypatch.setenv("MODELS_CONFIG_PATH", "~/.ikaros/config/models.json")
    monkeypatch.setenv("MEMORY_CONFIG_PATH", "~/.ikaros/config/memory.json")
    monkeypatch.setenv(
        "X_DEPLOYMENT_TARGETS_FILE", "~/.ikaros/config/deployment_targets.yaml"
    )

    assert app_paths.data_dir() == (tmp_path / ".ikaros" / "data").resolve()
    assert app_paths.models_config_path() == (
        tmp_path / ".ikaros" / "config" / "models.json"
    ).resolve()
    assert app_paths.memory_config_path() == (
        tmp_path / ".ikaros" / "config" / "memory.json"
    ).resolve()
    assert app_paths.deployment_targets_path() == (
        tmp_path / ".ikaros" / "config" / "deployment_targets.yaml"
    ).resolve()
