from pathlib import Path

from extension.skills.builtin.download_video.scripts.services import (
    browser_login_service,
    browser_session_store,
)


def test_login_platform_aliases_and_url_detection():
    assert browser_login_service.normalize_login_platform("抖音") == "douyin"
    assert browser_login_service.normalize_login_platform("微博") == "weibo"
    assert browser_login_service.normalize_login_platform("B站") == "bilibili"
    assert browser_login_service.normalize_login_platform("youtube") is None

    assert (
        browser_login_service.detect_login_platform("https://v.douyin.com/abc/")
        == "douyin"
    )
    assert (
        browser_login_service.detect_login_platform("https://m.weibo.cn/status/1")
        == "weibo"
    )
    assert (
        browser_login_service.detect_login_platform(
            "https://www.bilibili.com/video/BV1xx"
        )
        == "bilibili"
    )
    assert browser_login_service.detect_login_platform("https://example.com") is None


def test_browser_cookies_are_encrypted_and_materialized_temporarily(
    monkeypatch, tmp_path
):
    key_path = tmp_path / "sessions.key"
    session_path = tmp_path / "douyin.cookies.enc"
    monkeypatch.setattr(browser_session_store, "_key_path", lambda: key_path)
    monkeypatch.setattr(
        browser_session_store,
        "_session_path",
        lambda _user_id, _platform: session_path,
    )

    cookies = [
        {
            "name": "sessionid",
            "value": "secret-cookie-value",
            "domain": ".douyin.com",
            "path": "/",
            "expires": 2_000_000_000,
            "httpOnly": True,
            "secure": True,
            "sameSite": "None",
        }
    ]

    assert browser_session_store.save_browser_cookies("user-1", "douyin", cookies) == 1
    assert b"secret-cookie-value" not in session_path.read_bytes()
    assert browser_session_store.load_browser_cookies("user-1", "douyin") == cookies

    materialized_path = None
    with browser_session_store.materialized_cookie_file(
        "user-1", "douyin"
    ) as cookie_path:
        materialized_path = Path(str(cookie_path))
        assert materialized_path.exists()
        assert "secret-cookie-value" in materialized_path.read_text(encoding="utf-8")
        assert materialized_path.stat().st_mode & 0o777 == 0o600

    assert materialized_path is not None
    assert not materialized_path.exists()
