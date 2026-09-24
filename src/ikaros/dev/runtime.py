from __future__ import annotations

import asyncio
import contextlib
import os
import shlex
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import yaml

from core.state_paths import single_user_root
from ikaros.dev.acp_client import run_acp_backend


MAX_OUTPUT_CHARS = 12000
MAX_LOG_CHARS = 1_000_000


def _tail(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    payload = str(text or "")
    if len(payload) <= limit:
        return payload
    return payload[-limit:]


def _tail_for_log(text: str, limit: int = MAX_LOG_CHARS) -> str:
    payload = str(text or "")
    if len(payload) <= limit:
        return payload
    return payload[-limit:]


def _append_exec_log(
    *,
    log_path: str,
    command: List[str],
    cwd: str,
    timeout_sec: int,
    exit_code: int,
    stdout: str,
    stderr: str,
    timed_out: bool,
) -> None:
    safe_log_path = str(log_path or "").strip()
    if not safe_log_path:
        return

    try:
        target = Path(safe_log_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().astimezone().isoformat(timespec="seconds")
        lines = [
            f"[{stamp}] command={_command_to_text(command)} cwd={cwd}",
            f"timeout_sec={int(timeout_sec or 0)} timed_out={str(bool(timed_out)).lower()} exit_code={int(exit_code)}",
            "--- stdout ---",
            _tail_for_log(stdout),
            "--- stderr ---",
            _tail_for_log(stderr),
            "--- end ---",
            "",
        ]
        with target.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines))
    except Exception:
        return


def _as_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    token = str(value).strip().lower()
    if token in {"1", "true", "yes", "on"}:
        return True
    if token in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def _normalize_backend(raw: Any) -> str:
    token = str(raw or "").strip().lower()
    if token in {"gemini", "gemini_cli", "gemini-cli"}:
        return "gemini-cli"
    if token in {"hermes", "hermes-agent", ""}:
        return "hermes"
    raise ValueError(f"unsupported coding backend: {token}")


def _normalize_transport(raw: Any) -> str:
    token = str(raw or "").strip().lower()
    if token in {"acp", "agent-client-protocol"}:
        return "acp"
    return "cli"


def _backend_env_key(backend: str) -> str:
    safe_backend = _normalize_backend(backend)
    if safe_backend == "gemini-cli":
        return "GEMINI"
    return "HERMES"


def _default_transport_for_backend(backend: str) -> str:
    env_key = _backend_env_key(backend)
    specific = str(os.getenv(f"CODING_BACKEND_{env_key}_TRANSPORT", "") or "").strip()
    if specific:
        return _normalize_transport(specific)
    default = str(os.getenv("CODING_BACKEND_TRANSPORT_DEFAULT", "") or "").strip()
    if default:
        return _normalize_transport(default)
    if _normalize_backend(backend) in {"hermes", "gemini-cli"}:
        return "acp"
    return "cli"


def _build_coding_command(backend: str, instruction: str) -> tuple[str, List[str]]:
    safe_backend = _normalize_backend(backend)
    safe_instruction = str(instruction or "").strip()

    if safe_backend == "gemini-cli":
        cmd = str(
            os.getenv("CODING_BACKEND_GEMINI_COMMAND", "gemini-cli") or ""
        ).strip()
        template = str(
            os.getenv(
                "CODING_BACKEND_GEMINI_ARGS_TEMPLATE",
                "--model gemini-3.1-pro --prompt {instruction}",
            )
            or ""
        ).strip()
    else:
        raise ValueError(f"CLI transport is not supported for backend: {safe_backend}")

    rendered = template.format(instruction=shlex.quote(safe_instruction))
    args = shlex.split(rendered)
    return cmd, args


def _build_acp_command(
    backend: str,
    *,
    cwd: str,
) -> tuple[str, List[str], Dict[str, str]]:
    safe_backend = _normalize_backend(backend)
    safe_cwd = str(cwd or "").strip()
    if safe_backend == "hermes":
        cmd = str(os.getenv("CODING_BACKEND_HERMES_ACP_COMMAND", "hermes") or "").strip()
        template = str(
            os.getenv(
                "CODING_BACKEND_HERMES_ACP_ARGS_TEMPLATE",
                "acp",
            )
            or ""
        ).strip()
        env_overrides = {}
    elif safe_backend == "gemini-cli":
        cmd = str(
            os.getenv(
                "CODING_BACKEND_GEMINI_ACP_COMMAND",
                os.getenv("CODING_BACKEND_GEMINI_COMMAND", "gemini"),
            )
            or ""
        ).strip()
        template = str(
            os.getenv(
                "CODING_BACKEND_GEMINI_ACP_ARGS_TEMPLATE",
                "--experimental-acp",
            )
            or ""
        ).strip()
        env_overrides = {}
    else:
        raise ValueError(f"ACP transport is not supported for backend: {safe_backend}")

    rendered = template.format(cwd=shlex.quote(safe_cwd))
    args = shlex.split(rendered)
    return cmd, args, env_overrides


def _prepare_hermes_coding_home() -> Path:
    source = Path(os.getenv("HERMES_HOME") or Path.home() / ".hermes").resolve()
    target = (single_user_root() / "coding" / "hermes").resolve()
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    target.chmod(0o700)

    for child in source.iterdir():
        if child.name == "config.yaml":
            continue
        link = target / child.name
        if not link.exists() and not link.is_symlink():
            link.symlink_to(child, target_is_directory=child.is_dir())

    config_path = source / "config.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    model = config.get("model")
    if not isinstance(model, dict):
        model = {}
        config["model"] = model
    model["default"] = str(
        os.getenv("CODING_BACKEND_HERMES_MODEL", "gpt-5.6-sol") or "gpt-5.6-sol"
    ).strip()
    agent = config.get("agent")
    if not isinstance(agent, dict):
        agent = {}
        config["agent"] = agent
    agent["reasoning_effort"] = str(
        os.getenv("CODING_BACKEND_HERMES_REASONING_EFFORT", "max") or "max"
    ).strip()

    target_config = target / "config.yaml"
    temp_config = target / "config.yaml.tmp"
    temp_config.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    temp_config.chmod(0o600)
    temp_config.replace(target_config)
    return target


def _command_to_text(command: List[str]) -> str:
    return " ".join([shlex.quote(part) for part in command])


def _subprocess_env() -> Dict[str, str]:
    env = dict(os.environ)
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    env.setdefault("GCM_INTERACTIVE", "never")
    env.setdefault("CI", "true")
    env.setdefault("PAGER", "cat")
    env.setdefault("GIT_PAGER", "cat")
    env.setdefault(
        "GH_CONFIG_DIR",
        str((single_user_root() / "integrations" / "gh" / "config").resolve()),
    )
    env.setdefault(
        "GIT_CONFIG_GLOBAL",
        str((single_user_root() / "integrations" / "git" / ".gitconfig").resolve()),
    )
    env.setdefault("GH_NO_UPDATE_NOTIFIER", "1")
    return env


async def run_exec(
    command: List[str],
    *,
    cwd: str,
    timeout_sec: int = 1200,
    log_path: str = "",
) -> Dict[str, Any]:
    safe_command = [str(item) for item in list(command or []) if str(item)]
    if not safe_command:
        return {
            "ok": False,
            "error_code": "invalid_args",
            "message": "command is required",
        }
    safe_cwd = str(cwd or "").strip()
    if not safe_cwd:
        return {
            "ok": False,
            "error_code": "invalid_args",
            "message": "cwd is required",
        }

    try:
        proc = await asyncio.create_subprocess_exec(
            *safe_command,
            cwd=safe_cwd,
            env=_subprocess_env(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return {
            "ok": False,
            "error_code": "command_not_found",
            "message": f"command not found: {safe_command[0]}",
            "command": _command_to_text(safe_command),
            "cwd": safe_cwd,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "exec_prepare_failed",
            "message": str(exc),
            "command": _command_to_text(safe_command),
            "cwd": safe_cwd,
        }

    try:
        stdout_raw, stderr_raw = await asyncio.wait_for(
            proc.communicate(), timeout=max(1, int(timeout_sec or 1200))
        )
    except asyncio.TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        stdout_raw, stderr_raw = await proc.communicate()
        stdout_full = stdout_raw.decode("utf-8", errors="replace")
        stderr_full = stderr_raw.decode("utf-8", errors="replace")
        _append_exec_log(
            log_path=log_path,
            command=safe_command,
            cwd=safe_cwd,
            timeout_sec=int(timeout_sec or 0),
            exit_code=-1,
            stdout=stdout_full,
            stderr=stderr_full,
            timed_out=True,
        )
        stdout = _tail(stdout_full)
        stderr = _tail(stderr_full)
        return {
            "ok": False,
            "error_code": "timeout",
            "message": f"command timed out after {timeout_sec}s",
            "command": _command_to_text(safe_command),
            "cwd": safe_cwd,
            "exit_code": -1,
            "stdout": stdout,
            "stderr": stderr,
            "summary": _tail(stderr or stdout),
            "log_path": str(log_path or "").strip(),
        }

    stdout_full = stdout_raw.decode("utf-8", errors="replace")
    stderr_full = stderr_raw.decode("utf-8", errors="replace")
    _append_exec_log(
        log_path=log_path,
        command=safe_command,
        cwd=safe_cwd,
        timeout_sec=int(timeout_sec or 0),
        exit_code=int(proc.returncode or 0),
        stdout=stdout_full,
        stderr=stderr_full,
        timed_out=False,
    )
    stdout = _tail(stdout_full)
    stderr = _tail(stderr_full)
    summary = _tail((stderr or stdout).strip())
    return {
        "ok": int(proc.returncode or 0) == 0,
        "error_code": "" if int(proc.returncode or 0) == 0 else "command_failed",
        "message": "" if int(proc.returncode or 0) == 0 else summary,
        "command": _command_to_text(safe_command),
        "cwd": safe_cwd,
        "exit_code": int(proc.returncode or 0),
        "stdout": stdout,
        "stderr": stderr,
        "summary": summary,
        "log_path": str(log_path or "").strip(),
    }


async def run_shell(
    command: str,
    *,
    cwd: str,
    timeout_sec: int = 1200,
) -> Dict[str, Any]:
    safe_command = str(command or "").strip()
    if not safe_command:
        return {
            "ok": False,
            "error_code": "invalid_args",
            "message": "command is required",
        }
    safe_cwd = str(cwd or "").strip()
    if not safe_cwd:
        return {
            "ok": False,
            "error_code": "invalid_args",
            "message": "cwd is required",
        }

    try:
        proc = await asyncio.create_subprocess_shell(
            safe_command,
            cwd=safe_cwd,
            env=_subprocess_env(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "exec_prepare_failed",
            "message": str(exc),
            "command": safe_command,
            "cwd": safe_cwd,
        }

    try:
        stdout_raw, stderr_raw = await asyncio.wait_for(
            proc.communicate(), timeout=max(1, int(timeout_sec or 1200))
        )
    except asyncio.TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        stdout_raw, stderr_raw = await proc.communicate()
        stdout = _tail(stdout_raw.decode("utf-8", errors="replace"))
        stderr = _tail(stderr_raw.decode("utf-8", errors="replace"))
        return {
            "ok": False,
            "error_code": "timeout",
            "message": f"command timed out after {timeout_sec}s",
            "command": safe_command,
            "cwd": safe_cwd,
            "exit_code": -1,
            "stdout": stdout,
            "stderr": stderr,
            "summary": _tail(stderr or stdout),
        }

    stdout = _tail(stdout_raw.decode("utf-8", errors="replace"))
    stderr = _tail(stderr_raw.decode("utf-8", errors="replace"))
    summary = _tail((stderr or stdout).strip())
    return {
        "ok": int(proc.returncode or 0) == 0,
        "error_code": "" if int(proc.returncode or 0) == 0 else "command_failed",
        "message": "" if int(proc.returncode or 0) == 0 else summary,
        "command": safe_command,
        "cwd": safe_cwd,
        "exit_code": int(proc.returncode or 0),
        "stdout": stdout,
        "stderr": stderr,
        "summary": summary,
    }


async def run_coding_backend(
    *,
    instruction: str,
    backend: str,
    cwd: str,
    timeout_sec: int = 1800,
    source: str = "",
    log_path: str = "",
    transport: str = "",
    transport_session_id: str = "",
) -> Dict[str, Any]:
    safe_instruction = str(instruction or "").strip()
    if not safe_instruction:
        return {
            "ok": False,
            "error_code": "invalid_args",
            "message": "instruction is required",
        }

    configured_backend = backend or os.getenv("CODING_BACKEND_DEFAULT") or "hermes"
    try:
        backend_name = _normalize_backend(configured_backend)
    except ValueError as exc:
        return {
            "ok": False,
            "error_code": "unsupported_backend",
            "message": str(exc),
            "source": str(source or "").strip(),
        }
    transport_name = _normalize_transport(
        transport or _default_transport_for_backend(backend_name)
    )
    if backend_name == "hermes" and transport_name != "acp":
        return {
            "ok": False,
            "error_code": "unsupported_transport",
            "message": "Hermes coding backend requires ACP transport",
            "backend": backend_name,
            "transport": transport_name,
            "source": str(source or "").strip(),
        }
    if transport_name == "acp":
        try:
            cmd, args, env_overrides = _build_acp_command(
                backend_name,
                cwd=str(cwd or "").strip(),
            )
        except ValueError as exc:
            return {
                "ok": False,
                "error_code": "unsupported_transport",
                "message": str(exc),
                "backend": backend_name,
                "transport": "acp",
                "source": str(source or "").strip(),
            }
        env = _subprocess_env()
        env.update(env_overrides)
        if backend_name == "hermes":
            env["HERMES_HOME"] = str(_prepare_hermes_coding_home())
        result = await run_acp_backend(
            command=[cmd, *args],
            cwd=str(cwd or "").strip(),
            instruction=safe_instruction,
            timeout_sec=max(60, int(timeout_sec or 1800)),
            existing_session_id=str(transport_session_id or "").strip(),
            log_path=log_path,
            env=env,
            model=(
                str(os.getenv("CODING_BACKEND_HERMES_MODEL", "gpt-5.6-sol") or "")
                .strip()
                if backend_name == "hermes"
                else ""
            ),
            reasoning_effort=(
                str(
                    os.getenv("CODING_BACKEND_HERMES_REASONING_EFFORT", "max")
                    or ""
                ).strip()
                if backend_name == "hermes"
                else ""
            ),
        )
        result["backend"] = backend_name
        result["transport"] = "acp"
        result["source"] = str(source or "").strip()
        return result

    try:
        cmd, args = _build_coding_command(backend_name, safe_instruction)
    except ValueError as exc:
        return {
            "ok": False,
            "error_code": "unsupported_transport",
            "message": str(exc),
            "backend": backend_name,
            "transport": transport_name,
            "source": str(source or "").strip(),
        }
    first = await run_exec(
        [cmd, *args],
        cwd=str(cwd or "").strip(),
        timeout_sec=max(60, int(timeout_sec or 1800)),
        log_path=log_path,
    )
    first["backend"] = backend_name
    first["transport"] = "cli"
    first["source"] = str(source or "").strip()
    return first
