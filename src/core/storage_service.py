from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Callable, TypeVar

_state_io = importlib.import_module("core.state_io")
now_iso = _state_io.now_iso
read_json = _state_io.read_json
write_json = _state_io.write_json
next_id = _state_io.next_id

_state_paths = importlib.import_module("core.state_paths")
system_path = _state_paths.system_path
user_path = _state_paths.user_path

_KeyT = TypeVar("_KeyT")


def read_row_list(data: Any, *keys: str) -> list[dict[str, Any]]:
    rows: object = data
    if isinstance(data, dict):
        fallback_rows: object | None = None
        for key in keys:
            candidate = data.get(key)
            if isinstance(candidate, list):
                if candidate:
                    rows = candidate
                    break
                if fallback_rows is None:
                    fallback_rows = candidate
        else:
            if fallback_rows is not None:
                rows = fallback_rows
    if not isinstance(rows, list):
        return []
    return [item for item in rows if isinstance(item, dict)]


def dedupe_rows(
    rows: list[dict[str, Any]],
    *,
    key_fn: Callable[[dict[str, Any]], _KeyT],
) -> list[dict[str, Any]]:
    order: list[_KeyT] = []
    latest: dict[_KeyT, dict[str, Any]] = {}
    for row in rows:
        key = key_fn(row)
        if key not in latest:
            order.append(key)
        latest[key] = row
    return [latest[key] for key in order]


def max_row_id(rows: list[dict[str, Any]]) -> int:
    highest = 0
    for row in rows:
        try:
            highest = max(highest, int(row.get("id") or 0))
        except Exception:
            continue
    return highest


class StorageService:
    def user_path(self, user_id: int | str, *parts: str) -> Path:
        return user_path(user_id, *parts)

    def system_path(self, *parts: str) -> Path:
        return system_path(*parts)

    async def read(self, path: Path, default: Any) -> Any:
        return await read_json(path, default)

    async def write(self, path: Path, payload: Any) -> None:
        await write_json(path, payload)

    async def next_id(self, counter_name: str, *, start: int = 1) -> int:
        return await next_id(counter_name, start=start)

    async def next_id_after_store_rows(
        self,
        counter_name: str,
        path: Path,
        *,
        start: int = 1,
        list_keys: tuple[str, ...] = (),
    ) -> int:
        rows = read_row_list(await self.read(path, []), *list_keys)
        return await self.next_id(
            counter_name,
            start=max(start, max_row_id(rows) + 1),
        )


storage_service = StorageService()


def user_state_path(user_id: int | str, *parts: str) -> Path:
    return storage_service.user_path(user_id, *parts)


def system_state_path(*parts: str) -> Path:
    return storage_service.system_path(*parts)


__all__ = [
    "dedupe_rows",
    "max_row_id",
    "now_iso",
    "read_json",
    "read_row_list",
    "storage_service",
    "system_state_path",
    "user_state_path",
    "write_json",
]
