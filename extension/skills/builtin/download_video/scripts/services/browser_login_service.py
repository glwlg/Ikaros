from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from io import BytesIO
from typing import Any
from urllib.parse import urlparse

from .browser_session_store import save_browser_cookies

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoginProvider:
    key: str
    display_name: str
    login_url: str
    domains: tuple[str, ...]
    success_cookies: frozenset[str]
    qr_selectors: tuple[str, ...]
    open_login_dialog: bool = False


@dataclass(frozen=True)
class BrowserLoginResult:
    success: bool
    platform: str
    error_message: str = ""
    cookies_saved: int = 0


LOGIN_PROVIDERS = {
    "douyin": LoginProvider(
        key="douyin",
        display_name="抖音",
        login_url="https://www.douyin.com/",
        domains=("douyin.com", "iesdouyin.com", "bytedance.com"),
        success_cookies=frozenset({"sessionid", "sessionid_ss", "sid_guard", "uid_tt"}),
        qr_selectors=(
            "img[src^='data:image']",
            "img[src*='qrcode']",
        ),
        open_login_dialog=True,
    ),
    "weibo": LoginProvider(
        key="weibo",
        display_name="微博",
        login_url=(
            "https://passport.weibo.com/sso/signin"
            "?entry=miniblog&source=miniblog&disp=popup"
        ),
        domains=("weibo.com", "weibo.cn", "sina.com.cn"),
        success_cookies=frozenset({"SUB", "SUBP"}),
        qr_selectors=("img[src*='qr.weibo.cn']", "img[src*='qrcode']"),
    ),
    "bilibili": LoginProvider(
        key="bilibili",
        display_name="哔哩哔哩",
        login_url="https://passport.bilibili.com/login",
        domains=("bilibili.com",),
        success_cookies=frozenset({"SESSDATA", "bili_jct", "DedeUserID"}),
        qr_selectors=("img[alt='Scan me!']", "img[src^='data:image']"),
    ),
}

_ALIASES = {
    "抖音": "douyin",
    "dy": "douyin",
    "微博": "weibo",
    "wb": "weibo",
    "b站": "bilibili",
    "哔哩哔哩": "bilibili",
    "bili": "bilibili",
}


def normalize_login_platform(value: str) -> str | None:
    token = str(value or "").strip().lower()
    token = _ALIASES.get(token, token)
    return token if token in LOGIN_PROVIDERS else None


def detect_login_platform(url: str) -> str | None:
    try:
        host = (urlparse(str(url or "")).hostname or "").lower()
    except ValueError:
        return None
    for key, provider in LOGIN_PROVIDERS.items():
        if any(
            host == domain or host.endswith(f".{domain}") for domain in provider.domains
        ):
            return key
    return None


def _cookie_matches_provider(cookie: dict[str, Any], provider: LoginProvider) -> bool:
    domain = str(cookie.get("domain") or "").lower().lstrip(".")
    return any(
        domain == item or domain.endswith(f".{item}") for item in provider.domains
    )


def _is_login_complete(cookies: list[dict[str, Any]], provider: LoginProvider) -> bool:
    names = {str(item.get("name") or "") for item in cookies}
    return bool(names.intersection(provider.success_cookies))


def _upscale_qr_png(payload: bytes) -> bytes:
    try:
        from PIL import Image

        source = Image.open(BytesIO(payload)).convert("RGB")
        scale = max(1, 640 // max(source.size))
        if scale <= 1:
            return payload
        target = source.resize(
            (source.width * scale, source.height * scale),
            Image.Resampling.NEAREST,
        )
        output = BytesIO()
        target.save(output, format="PNG", optimize=False)
        return output.getvalue()
    except Exception:
        return payload


async def _open_login_page(page: Any, provider: LoginProvider) -> None:
    await page.goto(provider.login_url, wait_until="domcontentloaded", timeout=30_000)
    await page.wait_for_timeout(5_000 if provider.open_login_dialog else 1_500)
    if not provider.open_login_dialog:
        return

    for attempt in range(2):
        deadline = asyncio.get_running_loop().time() + 10
        while asyncio.get_running_loop().time() < deadline:
            buttons = page.get_by_text("登录", exact=True)
            for index in range(await buttons.count()):
                button = buttons.nth(index)
                try:
                    if await button.is_visible():
                        await button.click(timeout=3_000)
                        await page.wait_for_timeout(2_500)
                        return
                except Exception:
                    continue
            await page.wait_for_timeout(500)

        if attempt == 0:
            await page.goto(
                "https://www.douyin.com/jingxuan",
                wait_until="domcontentloaded",
                timeout=30_000,
            )
    raise RuntimeError("未找到登录入口")


async def _find_qr_image(page: Any, provider: LoginProvider) -> Any | None:
    for selector in provider.qr_selectors:
        matches = page.locator(selector)
        for index in range(await matches.count()):
            candidate = matches.nth(index)
            try:
                box = await candidate.bounding_box()
                if (
                    await candidate.is_visible()
                    and box
                    and min(box["width"], box["height"]) >= 100
                    and max(box["width"], box["height"])
                    / min(box["width"], box["height"])
                    <= 1.25
                ):
                    return candidate
            except Exception:
                continue

    candidates: list[tuple[float, Any]] = []
    images = page.locator("img")
    for index in range(await images.count()):
        candidate = images.nth(index)
        try:
            if not await candidate.is_visible():
                continue
            box = await candidate.bounding_box()
            if not box:
                continue
            width = float(box["width"])
            height = float(box["height"])
            if min(width, height) < 100 or max(width, height) > 320:
                continue
            if max(width, height) / min(width, height) > 1.2:
                continue
            source = str(await candidate.get_attribute("src") or "").lower()
            alt = str(await candidate.get_attribute("alt") or "").lower()
            score = min(width, height)
            if "qr" in source or "scan" in alt:
                score += 1_000
            elif source.startswith("data:image"):
                score += 500
            candidates.append((score, candidate))
        except Exception:
            continue
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


async def run_browser_login(
    ctx: Any,
    platform: str,
    user_id: int | str,
    *,
    timeout_seconds: int = 180,
) -> BrowserLoginResult:
    normalized = normalize_login_platform(platform)
    if not normalized:
        return BrowserLoginResult(
            success=False,
            platform=str(platform or ""),
            error_message="暂不支持该平台扫码登录。",
        )
    provider = LOGIN_PROVIDERS[normalized]

    try:
        from playwright.async_api import Error as PlaywrightError
        from playwright.async_api import async_playwright
    except ImportError:
        return BrowserLoginResult(
            success=False,
            platform=normalized,
            error_message="缺少 Playwright，请先安装浏览器登录依赖。",
        )

    browser = None
    try:
        async with async_playwright() as playwright:
            browser = await playwright.firefox.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 1280, "height": 900},
                locale="zh-CN",
            )
            page = await context.new_page()
            await _open_login_page(page, provider)
            qr_image = await _find_qr_image(page, provider)
            if qr_image is None:
                return BrowserLoginResult(
                    success=False,
                    platform=normalized,
                    error_message=f"未能从{provider.display_name}登录页识别二维码。",
                )

            qr_png = _upscale_qr_png(await qr_image.screenshot(type="png"))
            await ctx.reply_photo(
                qr_png,
                caption=(
                    f"请使用{provider.display_name}手机 App 扫码并确认登录。\n"
                    "二维码约 3 分钟后失效；成功后 Ikaros 会自动继续。"
                ),
                filename=f"{normalized}-login-qr.png",
            )

            loop = asyncio.get_running_loop()
            deadline = loop.time() + max(30, int(timeout_seconds))
            while loop.time() < deadline:
                cookies = await context.cookies()
                if _is_login_complete(cookies, provider):
                    await page.wait_for_timeout(1_000)
                    cookies = [
                        item
                        for item in await context.cookies()
                        if _cookie_matches_provider(item, provider)
                    ]
                    saved = save_browser_cookies(user_id, normalized, cookies)
                    return BrowserLoginResult(
                        success=True,
                        platform=normalized,
                        cookies_saved=saved,
                    )
                await asyncio.sleep(2)

            return BrowserLoginResult(
                success=False,
                platform=normalized,
                error_message="二维码已过期或等待扫码超时，请重新发起登录。",
            )
    except PlaywrightError as exc:
        lowered = str(exc).lower()
        if "executable doesn't exist" in lowered or "browser_type.launch" in lowered:
            message = "缺少 Playwright Firefox，请运行 `playwright install firefox`。"
        else:
            message = f"浏览器登录失败：{exc}"
        logger.warning(
            "Browser login failed for %s: %s", normalized, type(exc).__name__
        )
        return BrowserLoginResult(False, normalized, message)
    except Exception as exc:
        logger.warning(
            "Browser login failed for %s: %s", normalized, type(exc).__name__
        )
        return BrowserLoginResult(
            False,
            normalized,
            f"浏览器登录失败：{exc}",
        )
    finally:
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass
