from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from core.app_paths import data_dir, project_root
from core.runtime_v2 import RuntimeV2Store


def _timestamp() -> str:
    return datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")


def _copy_if_exists(src: Path, backup_root: Path, *, dry_run: bool) -> str:
    src = src.expanduser().resolve()
    if not src.exists():
        return "missing"
    rel_name = src.name if src.is_file() else src.as_posix().replace("/", "_")
    dst = backup_root / rel_name
    if dry_run:
        return str(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)
    return str(dst)


def prepare_runtime_v2_reset(
    *,
    root: Path | None = None,
    data_root: Path | None = None,
    backup_root: Path | None = None,
    reset_runtime: bool = True,
    dry_run: bool = True,
) -> dict[str, Any]:
    repo_root = (root or project_root()).expanduser().resolve()
    ikaros_data = (data_root or data_dir()).expanduser().resolve()
    backup_dir = (
        (backup_root.expanduser().resolve() if backup_root else ikaros_data / "backups")
        / f"runtime-v2-reset-{_timestamp()}"
    )

    paths = {
        "env": repo_root / ".env",
        "bot_data": ikaros_data / "bot_data.db",
        "accounting_state": ikaros_data / "user" / "accounting" / "state.md",
        "runtime_db": ikaros_data / "runtime.db",
        "runtime_db_wal": ikaros_data / "runtime.db-wal",
        "runtime_db_shm": ikaros_data / "runtime.db-shm",
    }
    backed_up = {
        name: _copy_if_exists(path, backup_dir, dry_run=dry_run)
        for name, path in paths.items()
        if name != "runtime_db" or path.exists()
    }

    removed: list[str] = []
    initialized = False
    if reset_runtime:
        for name in ("runtime_db", "runtime_db_wal", "runtime_db_shm"):
            path = paths[name]
            if path.exists():
                removed.append(str(path))
                if not dry_run:
                    path.unlink()
        if not dry_run:
            RuntimeV2Store(paths["runtime_db"]).list_sessions(limit=1)
            initialized = paths["runtime_db"].exists()
        else:
            initialized = True

    return {
        "dry_run": bool(dry_run),
        "project_root": str(repo_root),
        "data_root": str(ikaros_data),
        "backup_dir": str(backup_dir),
        "backed_up": backed_up,
        "removed": removed,
        "runtime_initialized": initialized,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backup accounting-critical files and reset Runtime v2 state."
    )
    parser.add_argument("--project-root", type=Path, default=project_root())
    parser.add_argument("--data-root", type=Path, default=data_dir())
    parser.add_argument("--backup-root", type=Path, default=None)
    parser.add_argument("--no-reset", action="store_true")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Actually copy backups and reset runtime.db. Without this, dry-run only.",
    )
    args = parser.parse_args(argv)
    result = prepare_runtime_v2_reset(
        root=args.project_root,
        data_root=args.data_root,
        backup_root=args.backup_root,
        reset_runtime=not args.no_reset,
        dry_run=not args.yes,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
