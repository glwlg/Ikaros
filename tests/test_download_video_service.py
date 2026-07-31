import pytest

from extension.skills.builtin.download_video.scripts.services import download_service


class _EmptyAsyncLines:
    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


class _Stderr:
    async def read(self):
        return b"ERROR: [Douyin] Fresh cookies (not necessarily logged in) are needed"


class _FailedProcess:
    stdout = _EmptyAsyncLines()
    stderr = _Stderr()
    returncode = 1

    async def wait(self):
        return self.returncode


class _ProgressMessage:
    def __init__(self):
        self.edits = []

    async def edit_text(self, text):
        self.edits.append(text)


@pytest.mark.asyncio
async def test_douyin_download_uses_single_video_mode_and_explains_cookie_error(
    monkeypatch, tmp_path
):
    captured_command = []

    async def fake_create_subprocess_exec(*command, **_kwargs):
        captured_command.extend(command)
        return _FailedProcess()

    monkeypatch.setattr(download_service, "DOWNLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(download_service, "COOKIES_FILE", str(tmp_path / "missing.txt"))
    monkeypatch.setattr(
        download_service.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    progress = _ProgressMessage()
    result = await download_service.download_video(
        "https://www.douyin.com/video/7298145681699622182",
        user_id=1,
        progress_message=progress,
    )

    assert "--no-playlist" in captured_command
    assert result.success is False
    assert result.error_message == download_service.DOUYIN_COOKIE_ERROR
    assert result.auth_required is True
    assert result.auth_platform == "douyin"
    assert progress.edits == [f"❌ 下载失败\n{download_service.DOUYIN_COOKIE_ERROR}"]
