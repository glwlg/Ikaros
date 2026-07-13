from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from core.app_paths import data_dir

DEFAULT_TITLE_LIMIT = 20
MAX_TITLE_LIMIT = 100


def article_publisher_data_dir() -> Path:
    return data_dir() / "user" / "skills" / "article_publisher"


def office_practice_history_path() -> Path:
    return article_publisher_data_dir() / "office_practice_history.jsonl"


def load_office_practice_records(
    *,
    limit: int = DEFAULT_TITLE_LIMIT,
    current_date: str = "",
    days: int | None = None,
) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), MAX_TITLE_LIMIT))
    path = office_practice_history_path()
    if not path.exists():
        return []

    cutoff: datetime | None = None
    if days is not None:
        try:
            base_date = (
                datetime.strptime(str(current_date or "").strip(), "%Y-%m-%d")
                if str(current_date or "").strip()
                else datetime.now()
            )
            cutoff = base_date - timedelta(days=days)
        except ValueError:
            cutoff = None

    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict):
            continue
        if cutoff is not None:
            published_at = str(item.get("published_date") or item.get("date") or "")[
                :10
            ]
            try:
                if (
                    published_at
                    and datetime.strptime(published_at, "%Y-%m-%d") < cutoff
                ):
                    continue
            except ValueError:
                pass
        records.append(item)
    return records[-safe_limit:]


def list_office_practice_titles(
    *, limit: int = DEFAULT_TITLE_LIMIT
) -> list[dict[str, str]]:
    records = load_office_practice_records(limit=limit)
    return [
        {
            "published_date": str(item.get("published_date") or item.get("date") or ""),
            "title": str(item.get("title") or ""),
        }
        for item in reversed(records)
        if str(item.get("title") or "").strip()
    ]


def save_article_draft(article_data: dict[str, Any]) -> Path:
    drafts_dir = article_publisher_data_dir() / "drafts"
    drafts_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = drafts_dir / f"{timestamp}.json"
    path.write_text(
        json.dumps(article_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path.resolve()
