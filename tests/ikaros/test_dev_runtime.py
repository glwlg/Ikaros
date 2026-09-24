import pytest

import ikaros.dev.runtime as runtime_module


def test_hermes_is_the_default_backend_and_uses_acp(monkeypatch):
    monkeypatch.delenv("CODING_BACKEND_DEFAULT", raising=False)
    monkeypatch.delenv("CODING_BACKEND_HERMES_TRANSPORT", raising=False)
    monkeypatch.delenv("CODING_BACKEND_TRANSPORT_DEFAULT", raising=False)

    assert runtime_module._normalize_backend("") == "hermes"
    assert runtime_module._default_transport_for_backend("hermes") == "acp"


def test_hermes_acp_command(monkeypatch):
    monkeypatch.delenv("CODING_BACKEND_HERMES_ACP_COMMAND", raising=False)
    monkeypatch.delenv("CODING_BACKEND_HERMES_ACP_ARGS_TEMPLATE", raising=False)

    cmd, args, env = runtime_module._build_acp_command("hermes", cwd="/tmp/repo")

    assert cmd == "hermes"
    assert args == ["acp"]
    assert env == {}


def test_gemini_acp_command_remains_supported(monkeypatch):
    monkeypatch.delenv("CODING_BACKEND_GEMINI_ACP_COMMAND", raising=False)
    monkeypatch.delenv("CODING_BACKEND_GEMINI_COMMAND", raising=False)
    monkeypatch.delenv("CODING_BACKEND_GEMINI_ACP_ARGS_TEMPLATE", raising=False)

    cmd, args, env = runtime_module._build_acp_command(
        "gemini-cli", cwd="/tmp/repo"
    )

    assert cmd == "gemini"
    assert args == ["--experimental-acp"]
    assert env == {}


def test_removed_backends_are_rejected():
    for backend in ("codex", "opencode", "open-code"):
        with pytest.raises(ValueError, match="unsupported coding backend"):
            runtime_module._normalize_backend(backend)


def test_subprocess_env_includes_persisted_gh_and_git_config(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    env = runtime_module._subprocess_env()

    assert env["GH_CONFIG_DIR"] == str(
        (tmp_path / "user" / "integrations" / "gh" / "config").resolve()
    )
    assert env["GIT_CONFIG_GLOBAL"] == str(
        (tmp_path / "user" / "integrations" / "git" / ".gitconfig").resolve()
    )
    assert env["GH_NO_UPDATE_NOTIFIER"] == "1"


@pytest.mark.asyncio
async def test_run_coding_backend_routes_hermes_with_model_and_reasoning(
    monkeypatch, tmp_path
):
    captured = {}
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))

    async def fake_run_acp_backend(
        *,
        command,
        cwd,
        instruction,
        timeout_sec,
        existing_session_id="",
        log_path="",
        env=None,
        model="",
        reasoning_effort="",
    ):
        captured.update(locals())
        return {
            "ok": True,
            "summary": "done",
            "stdout": "done",
            "transport_session_id": "acp-sess-1",
        }

    monkeypatch.setattr(runtime_module, "run_acp_backend", fake_run_acp_backend)

    result = await runtime_module.run_coding_backend(
        instruction="implement feature",
        backend="",
        cwd="/tmp",
        timeout_sec=120,
        source="test",
        transport_session_id="acp-sess-prev",
    )

    assert result["ok"] is True
    assert result["backend"] == "hermes"
    assert result["transport"] == "acp"
    assert captured["command"] == ["hermes", "acp"]
    assert captured["model"] == "gpt-5.6-sol"
    assert captured["reasoning_effort"] == "max"
    assert captured["existing_session_id"] == "acp-sess-prev"
    coding_home = tmp_path / "data" / "user" / "coding" / "hermes"
    config = runtime_module.yaml.safe_load(
        (coding_home / "config.yaml").read_text(encoding="utf-8")
    )
    assert config["model"]["default"] == "gpt-5.6-sol"
    assert config["agent"]["reasoning_effort"] == "max"


@pytest.mark.asyncio
async def test_run_coding_backend_rejects_removed_backend():
    result = await runtime_module.run_coding_backend(
        instruction="implement feature",
        backend="codex",
        cwd="/tmp",
    )

    assert result["ok"] is False
    assert result["error_code"] == "unsupported_backend"


@pytest.mark.asyncio
async def test_run_coding_backend_rejects_non_acp_transport():
    result = await runtime_module.run_coding_backend(
        instruction="implement feature",
        backend="hermes",
        transport="cli",
        cwd="/tmp",
    )

    assert result["ok"] is False
    assert result["error_code"] == "unsupported_transport"
