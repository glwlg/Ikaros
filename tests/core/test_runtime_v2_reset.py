from __future__ import annotations

from pathlib import Path

from scripts.runtime_v2_reset import prepare_runtime_v2_reset


def test_runtime_v2_reset_backs_up_accounting_inputs_and_reinitializes_runtime(
    tmp_path,
):
    repo_root = tmp_path / "repo"
    data_root = tmp_path / "data"
    backup_root = tmp_path / "backups"
    repo_root.mkdir()
    (repo_root / ".env").write_text("IKAROS_KERNEL=codex\n", encoding="utf-8")
    data_root.mkdir()
    (data_root / "bot_data.db").write_bytes(b"bot-db")
    accounting_state = data_root / "user" / "accounting" / "state.md"
    accounting_state.parent.mkdir(parents=True)
    accounting_state.write_text("active_book: default\n", encoding="utf-8")
    (data_root / "runtime.db").write_bytes(b"old runtime")

    result = prepare_runtime_v2_reset(
        root=repo_root,
        data_root=data_root,
        backup_root=backup_root,
        dry_run=False,
    )

    backup_dir = Path(result["backup_dir"])
    assert (backup_dir / ".env").read_text(encoding="utf-8") == "IKAROS_KERNEL=codex\n"
    assert (backup_dir / "bot_data.db").read_bytes() == b"bot-db"
    assert (backup_dir / "state.md").read_text(encoding="utf-8") == (
        "active_book: default\n"
    )
    assert result["runtime_initialized"] is True
    assert (data_root / "runtime.db").exists()
    assert (data_root / "runtime.db").read_bytes() != b"old runtime"
    assert (data_root / "bot_data.db").read_bytes() == b"bot-db"
    assert accounting_state.read_text(encoding="utf-8") == "active_book: default\n"


def test_runtime_v2_reset_dry_run_does_not_touch_files(tmp_path):
    repo_root = tmp_path / "repo"
    data_root = tmp_path / "data"
    repo_root.mkdir()
    data_root.mkdir()
    (repo_root / ".env").write_text("dry=true\n", encoding="utf-8")
    (data_root / "runtime.db").write_bytes(b"old runtime")

    result = prepare_runtime_v2_reset(
        root=repo_root,
        data_root=data_root,
        dry_run=True,
    )

    assert result["dry_run"] is True
    assert result["runtime_initialized"] is True
    assert (data_root / "runtime.db").read_bytes() == b"old runtime"
