from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
LEDGER_PATH = REPO_ROOT / "docs" / "runtime_v2_test_ledger.md"


def test_runtime_v2_test_ledger_references_existing_tests():
    body = LEDGER_PATH.read_text(encoding="utf-8")
    assert "静态检查只能作为辅助证据" in body
    refs = re.findall(r"`(tests/[^`]+?\.py)::(test_[A-Za-z0-9_]+)`", body)
    assert refs

    missing: list[str] = []
    for rel_path, test_name in refs:
        path = REPO_ROOT / rel_path
        if not path.exists():
            missing.append(f"{rel_path} is missing")
            continue
        if f"def {test_name}" not in path.read_text(encoding="utf-8"):
            missing.append(f"{rel_path}::{test_name} is missing")
    assert not missing, "\n".join(missing)
