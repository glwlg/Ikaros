"""WeChat Official Account publisher."""

from __future__ import annotations

import io
import logging
import re
import shutil
import subprocess
import tempfile
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

WECHAT_COVER_MAX_BYTES = 2 * 1024 * 1024
WECHAT_ARTICLE_IMAGE_MAX_BYTES = 1 * 1024 * 1024


class WeChatPublisher:
    BASE_URL = "https://api.weixin.qq.com/cgi-bin"

    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self.access_token: str | None = None
        self.token_expiry = 0.0

    async def get_access_token(self) -> str:
        if self.access_token and time.time() < self.token_expiry:
            return self.access_token

        url = f"{self.BASE_URL}/token"
        params = {
            "grant_type": "client_credential",
            "appid": self.app_id,
            "secret": self.app_secret,
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            if "access_token" not in data:
                raise RuntimeError(f"Failed to get access token: {data}")
            self.access_token = data["access_token"]
            self.token_expiry = time.time() + data.get("expires_in", 7200) - 200
            return self.access_token

    async def upload_cover_image(
        self,
        image_bytes: bytes,
        filename: str = "cover.png",
    ) -> str:
        token = await self.get_access_token()
        url = f"{self.BASE_URL}/material/add_material?access_token={token}&type=image"
        prepared_bytes, prepared_name, content_type = prepare_wechat_upload_image(
            image_bytes,
            filename=filename,
            max_bytes=WECHAT_COVER_MAX_BYTES,
            max_width=900,
        )
        files = {"media": (prepared_name, prepared_bytes, content_type)}

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, files=files)
            resp.raise_for_status()
            data = resp.json()
            if "media_id" not in data:
                raise RuntimeError(f"Failed to upload cover: {data}")
            return str(data["media_id"])

    async def upload_article_image(
        self,
        image_bytes: bytes,
        filename: str = "image.png",
    ) -> str:
        token = await self.get_access_token()
        url = f"{self.BASE_URL}/media/uploadimg?access_token={token}"
        prepared_bytes, prepared_name, content_type = prepare_wechat_upload_image(
            image_bytes,
            filename=filename,
            max_bytes=WECHAT_ARTICLE_IMAGE_MAX_BYTES,
            max_width=1200,
        )
        files = {"media": (prepared_name, prepared_bytes, content_type)}

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, files=files)
            resp.raise_for_status()
            data = resp.json()
            if "url" not in data:
                raise RuntimeError(f"Failed to upload article image: {data}")
            return str(data["url"])

    async def add_draft(
        self,
        *,
        title: str,
        content_html: str,
        thumb_media_id: str,
        author: str = "Ikaros",
        digest: str = "",
    ) -> str:
        token = await self.get_access_token()
        url = f"{self.BASE_URL}/draft/add?access_token={token}"
        payload = {
            "articles": [
                {
                    "title": title,
                    "author": author,
                    "digest": digest,
                    "content": content_html,
                    "content_source_url": "",
                    "thumb_media_id": thumb_media_id,
                    "need_open_comment": 1,
                    "only_fans_can_comment": 0,
                }
            ]
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            if "media_id" in data:
                return str(data["media_id"])
            if data.get("errcode") == 0:
                return "success"
            raise RuntimeError(f"Failed to add draft: {data}")

    async def get_draft(self, media_id: str) -> dict[str, Any]:
        token = await self.get_access_token()
        url = f"{self.BASE_URL}/draft/get?access_token={token}"
        payload = {"media_id": str(media_id or "").strip()}

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            if "news_item" in data:
                return data
            raise RuntimeError(f"Failed to get draft: {data}")


# ---------------------------------------------------------------------------
# Publish helpers
# ---------------------------------------------------------------------------

def prepare_wechat_upload_image(
    image_bytes: bytes,
    *,
    filename: str,
    max_bytes: int,
    max_width: int,
) -> tuple[bytes, str, str]:
    """Return image bytes small enough for WeChat upload endpoints."""
    payload = bytes(image_bytes or b"")
    safe_filename = str(filename or "image.png").strip() or "image.png"
    if payload and len(payload) <= max_bytes:
        return payload, safe_filename, _guess_image_content_type(safe_filename, payload)

    try:
        from PIL import Image  # type: ignore
    except Exception:
        compressed = _compress_image_with_imagemagick(
            payload,
            max_bytes=max_bytes,
            max_width=max_width,
        )
        if compressed:
            return compressed, _with_jpg_suffix(safe_filename), "image/jpeg"
        if not payload:
            return payload, safe_filename, _guess_image_content_type(safe_filename, payload)
        raise RuntimeError(f"图片大小 {len(payload)} bytes 超过微信上传限制 {max_bytes} bytes，无法自动压缩。")

    with Image.open(io.BytesIO(payload)) as image:
        image = image.convert("RGB")
        if image.width > max_width:
            ratio = max_width / float(image.width)
            height = max(1, int(image.height * ratio))
            resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
            image = image.resize((max_width, height), resample)

        for quality in (86, 78, 70, 62, 54, 46):
            out = io.BytesIO()
            image.save(out, format="JPEG", quality=quality, optimize=True)
            compressed = out.getvalue()
            if len(compressed) <= max_bytes:
                return compressed, _with_jpg_suffix(safe_filename), "image/jpeg"

    raise RuntimeError(
        f"图片压缩后仍超过微信上传限制 {max_bytes} bytes，请更换更小的配图。"
    )


def _guess_image_content_type(filename: str, payload: bytes) -> str:
    suffix = str(filename or "").rsplit(".", 1)[-1].lower()
    if suffix in {"jpg", "jpeg"} or payload.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if suffix == "gif" or payload.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    return "image/png"


def _with_jpg_suffix(filename: str) -> str:
    stem = str(filename or "image").rsplit(".", 1)[0].strip() or "image"
    return f"{stem}.jpg"


def _compress_image_with_imagemagick(
    payload: bytes,
    *,
    max_bytes: int,
    max_width: int,
) -> bytes:
    binary = shutil.which("magick") or shutil.which("convert")
    if not binary or not payload:
        return b""

    with tempfile.TemporaryDirectory(prefix="wechat-image-") as tmp_dir:
        in_path = f"{tmp_dir}/input.img"
        out_path = f"{tmp_dir}/output.jpg"
        with open(in_path, "wb") as handle:
            handle.write(payload)

        command_prefix = [binary]
        if binary.endswith("magick"):
            command_prefix = [binary]

        for quality in (86, 78, 70, 62, 54, 46):
            cmd = [
                *command_prefix,
                in_path,
                "-resize",
                f"{int(max_width)}x>",
                "-strip",
                "-quality",
                str(quality),
                out_path,
            ]
            try:
                subprocess.run(
                    cmd,
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=30,
                )
                with open(out_path, "rb") as handle:
                    compressed = handle.read()
            except Exception:
                continue
            if compressed and len(compressed) <= max_bytes:
                return compressed
    return b""

def format_wechat_inline_image_html(image_url: str) -> str:
    safe_url = str(image_url or "").strip()
    return (
        '<p style="margin:18px 0 20px;text-align:center;">'
        f'<img src="{safe_url}" '
        'style="display:block;width:100%;height:auto;border-radius:6px;"/>'
        "</p>"
    )


def summarize_wechat_style_roundtrip(
    *,
    original_html: str,
    draft_data: dict[str, Any],
) -> str:
    original_style_count = str(original_html or "").count("style=")
    if original_style_count <= 0:
        return ""

    items = draft_data.get("news_item")
    if not isinstance(items, list) or not items:
        return "⚠️ 样式回读未返回正文内容。"

    saved_html = str((items[0] or {}).get("content") or "")
    saved_style_count = saved_html.count("style=")
    if saved_style_count > 0:
        return f"样式回读已保留（style {saved_style_count}/{original_style_count}）。"
    return "⚠️ 样式回读未发现 `style`，公众号后台可能已清洗排版。"


async def verify_wechat_style_roundtrip(
    *,
    publisher: WeChatPublisher,
    draft_id: str,
    original_html: str,
) -> str:
    if not str(draft_id or "").strip() or str(draft_id).strip() == "success":
        return ""
    try:
        draft_data = await publisher.get_draft(draft_id)
    except Exception as exc:
        logger.warning("WeChat draft style roundtrip check failed: %s", exc)
        return ""
    return summarize_wechat_style_roundtrip(
        original_html=original_html,
        draft_data=draft_data,
    )

async def publish_to_wechat(
    *,
    publisher: WeChatPublisher,
    article_data: dict[str, Any],
    cover_bytes: bytes | None,
    section_images: dict[int, bytes],
    account_name: str = "",
) -> str:
    thumb_media_id = None
    if cover_bytes:
        thumb_media_id = await publisher.upload_cover_image(cover_bytes)

    full_html = ""
    for idx, sec in enumerate(article_data["sections"]):
        full_html += str(sec.get("content", ""))
        if idx not in section_images:
            continue
        try:
            image_url = await publisher.upload_article_image(section_images[idx])
            full_html += format_wechat_inline_image_html(image_url)
        except Exception as exc:
            logger.error("Failed to upload inline image %s: %s", idx, exc)

    if not thumb_media_id:
        return "❌ 发布中止：封面图生成或上传失败。"

    digest_text = str(article_data.get("digest") or "")
    if len(digest_text) > 50:
        digest_text = digest_text[:50] + "..."
    if not full_html:
        full_html = "<p>Empty content.</p>"

    draft_id = await publisher.add_draft(
        title=article_data["title"],
        content_html=full_html,
        thumb_media_id=thumb_media_id,
        author=article_data["author"],
        digest=digest_text,
    )
    style_status = await verify_wechat_style_roundtrip(
        publisher=publisher,
        draft_id=draft_id,
        original_html=full_html,
    )
    suffix = f"；{style_status}" if style_status else ""
    if str(account_name or "").strip():
        return f"✅ 已发布到公众号草稿箱（{account_name}），MediaID: `{draft_id}`{suffix}"
    return f"✅ 已发布到公众号草稿箱，MediaID: `{draft_id}`{suffix}"


def format_wechat_publish_preflight_error(exc: Exception) -> str:
    raw = str(exc or "").strip()
    errcode_match = re.search(r"'errcode':\s*(\d+)", raw)
    ip_match = re.search(r"invalid ip\s+([0-9a-fA-F:\.\-]+)", raw, flags=re.IGNORECASE)
    errcode = errcode_match.group(1) if errcode_match else ""
    ip = ip_match.group(1) if ip_match else ""

    if errcode == "40164":
        details = "当前服务器出口 IP 不在微信公众号白名单中"
        if ip:
            details += f"：`{ip}`"
        return (
            "❌ 发布前检查失败："
            f"{details}。\n"
            "请先把该 IP 加入公众号后台白名单，再重新执行发布。"
        )
    return f"❌ 发布前检查失败：{raw or '无法获取公众号 access token'}"


async def prepare_wechat_publisher(
    account: dict[str, Any] | None,
) -> tuple[WeChatPublisher | None, str]:
    if not account:
        return None, "⚠️ 发布中止：未配置公众号凭证 `wechat_official_account`。"

    app_id = account.get("app_id") if isinstance(account, dict) else None
    app_secret = account.get("app_secret") if isinstance(account, dict) else None
    if not app_id or not app_secret:
        return None, "⚠️ 发布中止：公众号凭证缺少 `app_id` 或 `app_secret`。"

    publisher = WeChatPublisher(str(app_id), str(app_secret))
    try:
        await publisher.get_access_token()
    except Exception as exc:
        logger.error("WeChat publish preflight failed: %s", exc, exc_info=True)
        return None, format_wechat_publish_preflight_error(exc)
    return publisher, ""
