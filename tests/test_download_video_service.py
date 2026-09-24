import hashlib
from types import SimpleNamespace

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


class _SuccessfulStderr:
    async def read(self):
        return b""


class _SuccessfulProcess:
    stdout = _EmptyAsyncLines()
    stderr = _SuccessfulStderr()
    returncode = 0

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

    async def fake_douyin_session(_url, *, initial_cookies=None):
        assert initial_cookies is None
        return SimpleNamespace(
            cookies=[
                {
                    "name": "s_v_web_id",
                    "value": "anonymous-session",
                    "domain": ".douyin.com",
                    "path": "/",
                }
            ],
            user_agent="anonymous-browser-agent",
        )

    async def fake_create_subprocess_exec(*command, **_kwargs):
        captured_command.extend(command)
        return _FailedProcess()

    monkeypatch.setattr(download_service, "DOWNLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(download_service, "COOKIES_FILE", str(tmp_path / "missing.txt"))
    monkeypatch.setattr(
        download_service,
        "create_douyin_download_session",
        fake_douyin_session,
    )
    monkeypatch.setattr(
        download_service,
        "load_browser_cookies",
        lambda _user_id, _platform: [],
    )
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
    assert "--cookies" in captured_command
    assert captured_command[captured_command.index("--user-agent") + 1] == (
        "anonymous-browser-agent"
    )
    assert result.success is False
    assert result.error_message == download_service.DOUYIN_COOKIE_ERROR
    assert result.auth_required is True
    assert result.auth_platform == "douyin"
    assert progress.edits == [f"❌ 下载失败\n{download_service.DOUYIN_COOKIE_ERROR}"]


@pytest.mark.asyncio
async def test_douyin_retries_saved_login_only_after_anonymous_failure(
    monkeypatch, tmp_path
):
    url = "https://www.douyin.com/video/7298145681699622182"
    expected_path = tmp_path / f"video_{hashlib.md5(url.encode()).hexdigest()}.mp4"
    saved_cookies = [
        {
            "name": "sessionid",
            "value": "saved-login",
            "domain": ".douyin.com",
            "path": "/",
        }
    ]
    session_inputs = []
    commands = []

    async def fake_douyin_session(_url, *, initial_cookies=None):
        session_inputs.append(initial_cookies)
        return SimpleNamespace(
            cookies=[
                {
                    "name": "s_v_web_id",
                    "value": "fresh-session",
                    "domain": ".douyin.com",
                    "path": "/",
                }
            ],
            user_agent="authenticated-agent" if initial_cookies else "anonymous-agent",
        )

    async def fake_create_subprocess_exec(*command, **_kwargs):
        commands.append(command)
        if len(commands) == 1:
            return _FailedProcess()
        expected_path.write_bytes(b"video")
        return _SuccessfulProcess()

    monkeypatch.setattr(download_service, "DOWNLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        download_service,
        "create_douyin_download_session",
        fake_douyin_session,
    )
    monkeypatch.setattr(
        download_service,
        "load_browser_cookies",
        lambda _user_id, _platform: saved_cookies,
    )
    monkeypatch.setattr(
        download_service.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    progress = _ProgressMessage()
    result = await download_service.download_video(
        url,
        user_id=1,
        progress_message=progress,
    )

    assert result.success is True
    assert session_inputs == [None, saved_cookies]
    assert len(commands) == 2
    assert commands[0][commands[0].index("--user-agent") + 1] == "anonymous-agent"
    assert commands[1][commands[1].index("--user-agent") + 1] == ("authenticated-agent")
    assert progress.edits == ["✅ 下载完成，正在上传..."]
