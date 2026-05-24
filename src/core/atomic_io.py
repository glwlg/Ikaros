from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    tmp.write_text(content, encoding=encoding)
    tmp.replace(target)


class SyncFileLock:
    def __init__(
        self,
        lock_path: Path,
        *,
        timeout_sec: float = 8.0,
        poll_sec: float = 0.05,
        stale_sec: float = 300.0,
    ) -> None:
        self.lock_path = Path(lock_path)
        self.timeout_sec = max(0.2, float(timeout_sec))
        self.poll_sec = max(0.01, float(poll_sec))
        self.stale_sec = max(self.timeout_sec * 2.0, float(stale_sec))
        self._held = False

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        if int(pid) <= 0:
            return False
        try:
            os.kill(int(pid), 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except Exception:
            return True
        return True

    def _read_lock_pid(self) -> int | None:
        try:
            raw = self.lock_path.read_text(encoding="utf-8")
        except Exception:
            return None
        for line in raw.splitlines():
            if not line.startswith("pid="):
                continue
            value = line.partition("=")[2].strip()
            if not value:
                return None
            try:
                return int(value)
            except Exception:
                return None
        return None

    def _is_stale(self) -> bool:
        pid = self._read_lock_pid()
        if pid is not None:
            return not self._pid_alive(pid)
        try:
            mtime = float(self.lock_path.stat().st_mtime)
        except Exception:
            return False
        return max(0.0, time.time() - mtime) >= self.stale_sec

    def _cleanup_stale_lock(self) -> bool:
        if not self._is_stale():
            return False
        try:
            self.lock_path.unlink()
            return True
        except FileNotFoundError:
            return True
        except Exception:
            return False

    def __enter__(self) -> "SyncFileLock":
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout_sec
        while True:
            try:
                fd = os.open(
                    str(self.lock_path),
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o644,
                )
                now = time.time()
                os.write(
                    fd,
                    f"pid={os.getpid()}\ncreated_at={now:.6f}\n".encode("utf-8"),
                )
                os.close(fd)
                self._held = True
                return self
            except FileExistsError:
                if self._cleanup_stale_lock():
                    continue
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"file lock timeout: {self.lock_path}")
                time.sleep(self.poll_sec)

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self._held:
            try:
                self.lock_path.unlink(missing_ok=True)
            except Exception:
                pass
        self._held = False
        return False


@contextmanager
def sync_file_lock(
    lock_path: Path,
    *,
    timeout_sec: float = 8.0,
    poll_sec: float = 0.05,
    stale_sec: float = 300.0,
) -> Iterator[SyncFileLock]:
    with SyncFileLock(
        lock_path,
        timeout_sec=timeout_sec,
        poll_sec=poll_sec,
        stale_sec=stale_sec,
    ) as lock:
        yield lock
