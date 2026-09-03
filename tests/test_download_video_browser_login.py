from pathlib import Path

import pytest

from extension.skills.builtin.download_video.scripts.services import (
    browser_login_service,
    browser_session_store,
)


class _FakeImage:
    def __init__(self, *, visible=True, width=178, height=178):
        self.visible = visible
        self.box = {"width": width, "height": height}

    async def is_visible(self):
        return self.visible

    async def bounding_box(self):
        return self.box


class _FakeLocator:
    def __init__(self, items):
        self.items = items

    async def count(self):
        return len(self.items)

    def nth(self, index):
        return self.items[index]


class _FakePage:
    def __init__(self, matches):
        self.matches = matches
        self.waits = []

    def locator(self, selector):
        return _FakeLocator(self.matches.get(selector, []))

    async def wait_for_timeout(self, milliseconds):
        self.waits.append(milliseconds)


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


@pytest.mark.asyncio
async def test_douyin_qr_detection_rejects_generic_square_image():
    promo = _FakeImage(width=128, height=123)
    page = _FakePage({"img": [promo]})

    result = await browser_login_service._find_qr_image(
        page, browser_login_service.LOGIN_PROVIDERS["douyin"]
    )

    assert result is None


@pytest.mark.asyncio
async def test_douyin_qr_detection_accepts_semantic_qr_image():
    qr_image = _FakeImage()
    page = _FakePage({"img[aria-label*='二维码']": [qr_image]})

    result = await browser_login_service._find_qr_image(
        page, browser_login_service.LOGIN_PROVIDERS["douyin"]
    )

    assert result is qr_image


@pytest.mark.asyncio
async def test_wait_for_qr_image_retries_until_qr_is_visible(monkeypatch):
    qr_image = _FakeImage()
    results = iter((None, None, qr_image))

    async def find_qr_image(_page, _provider):
        return next(results)

    monkeypatch.setattr(browser_login_service, "_find_qr_image", find_qr_image)
    page = _FakePage({})

    result = await browser_login_service._wait_for_qr_image(
        page,
        browser_login_service.LOGIN_PROVIDERS["douyin"],
        timeout_seconds=1,
    )

    assert result is qr_image
    assert page.waits == [500, 500]


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
