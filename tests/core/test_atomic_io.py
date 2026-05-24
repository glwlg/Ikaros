from core.atomic_io import SyncFileLock, atomic_write_text


def test_atomic_write_text_replaces_existing_file(tmp_path):
    target = tmp_path / "state" / "payload.json"
    atomic_write_text(target, '{"version": 1}\n')
    atomic_write_text(target, '{"version": 2}\n')

    assert target.read_text(encoding="utf-8") == '{"version": 2}\n'
    assert not list(target.parent.glob("*.tmp"))


def test_sync_file_lock_cleans_stale_pid_lock(tmp_path):
    lock_path = tmp_path / "state.json.lock"
    lock_path.write_text("pid=-1\ncreated_at=1\n", encoding="utf-8")

    with SyncFileLock(lock_path, timeout_sec=0.2):
        assert lock_path.exists()

    assert not lock_path.exists()
