from core.local_file_delivery import validate_local_delivery_target


def test_validate_local_delivery_target_resolves_relative_file(tmp_path):
    target = (tmp_path / "docs" / "report.txt").resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("hello", encoding="utf-8")

    resolved, error = validate_local_delivery_target(
        "docs/report.txt",
        task_workspace_root=str(tmp_path),
        platform="telegram",
    )

    assert resolved == target
    assert error == ""


def test_validate_local_delivery_target_blocks_sensitive_env_file(tmp_path):
    sensitive = (tmp_path / ".env").resolve()
    sensitive.write_text("SECRET=1\n", encoding="utf-8")

    resolved, error = validate_local_delivery_target(
        str(sensitive),
        task_workspace_root=str(tmp_path),
        platform="telegram",
    )

    assert resolved is None
    assert "environment file blocked" in error


def test_validate_local_delivery_target_allows_readable_absolute_path(tmp_path):
    workspace_root = (tmp_path / "workspace").resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)
    external = (tmp_path / "shared" / "baby_latest.jpg").resolve()
    external.parent.mkdir(parents=True, exist_ok=True)
    external.write_bytes(b"fake-image")

    resolved, error = validate_local_delivery_target(
        str(external),
        task_workspace_root=str(workspace_root),
        platform="telegram",
    )

    assert resolved == external
    assert error == ""


def test_validate_local_delivery_target_uses_platform_specific_size_limit(
    monkeypatch, tmp_path
):
    monkeypatch.delenv("LOCAL_FILE_DELIVERY_MAX_FILE_MB", raising=False)
    monkeypatch.delenv("LOCAL_FILE_DELIVERY_MAX_FILE_MB_TELEGRAM", raising=False)
    monkeypatch.delenv("LOCAL_FILE_DELIVERY_MAX_FILE_MB_WEIXIN", raising=False)
    target = (tmp_path / "large-video.mp4").resolve()
    with target.open("wb") as file_obj:
        file_obj.truncate(50 * 1024 * 1024)

    weixin_path, weixin_error = validate_local_delivery_target(
        str(target),
        task_workspace_root=str(tmp_path),
        platform="weixin",
    )
    telegram_path, telegram_error = validate_local_delivery_target(
        str(target),
        task_workspace_root=str(tmp_path),
        platform="telegram",
    )

    assert weixin_path == target
    assert weixin_error == ""
    assert telegram_path is None
    assert "too large" in telegram_error
