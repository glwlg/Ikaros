from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import logging
import re
import struct
import time
import zlib
from datetime import datetime
from os import urandom
from pathlib import Path
from secrets import randbits, token_hex
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from urllib.parse import unquote, urlparse

import httpx

from core.config import DATA_DIR, WEIXIN_DEBUG_UPDATES
from core.platform.adapter import BotAdapter
from core.platform.exceptions import MediaDownloadUnavailableError, MessageSendError
from core.platform.models import UnifiedContext

from .formatter import markdown_to_weixin_text
from .mapper import map_weixin_message
from .media import (
    DEFAULT_CDN_BASE_URL,
    WEIXIN_MEDIA_MAX_BYTES,
    UploadedWeixinMedia,
    aes_ecb_padded_size,
    build_cdn_download_url,
    build_cdn_upload_url,
    build_file_message_item,
    build_image_message_item,
    build_video_message_item,
    classify_media_kind,
    decrypt_aes_ecb,
    default_suffix_for_mime,
    encrypt_aes_ecb,
    extension_from_content_type_or_url,
    guess_mime_type,
    normalize_cdn_base_url,
    parse_aes_key_base64,
    upload_media_type_for_kind,
)

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://ilinkai.weixin.qq.com/"
DEFAULT_TEXT_CHUNK_LIMIT = 2000
DEFAULT_POLL_BACKOFF_SEC = 30
DEFAULT_POLL_RETRY_SEC = 2
DEFAULT_MAX_FAILURES = 3
DEFAULT_TYPING_CACHE_TTL_SEC = 24 * 60 * 60
DEFAULT_TYPING_CANCEL_DELAY_SEC = 6
WEIXIN_TYPING_STATUS_TYPING = 1
WEIXIN_TYPING_STATUS_CANCEL = 2
CALLBACK_PREFIX = "#"


class WeixinAdapter(BotAdapter):
    """Weixin iLink Bot adapter using QR login and HTTP long-poll."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        cdn_base_url: str = DEFAULT_CDN_BASE_URL,
        login_timeout_sec: int = 300,
        login_poll_interval_sec: int = 3,
        text_chunk_limit: int = DEFAULT_TEXT_CHUNK_LIMIT,
    ):
        super().__init__("weixin")
        self.base_url = self._normalize_base_url(base_url)
        self.cdn_base_url = normalize_cdn_base_url(cdn_base_url)
        self.login_timeout_sec = max(30, int(login_timeout_sec or 300))
        self.login_poll_interval_sec = max(1, int(login_poll_interval_sec or 3))
        self.text_chunk_limit = max(
            200,
            min(
                int(text_chunk_limit or DEFAULT_TEXT_CHUNK_LIMIT),
                DEFAULT_TEXT_CHUNK_LIMIT,
            ),
        )

        self.state_dir = Path(DATA_DIR) / "weixin"
        self.bindings_path = self.state_dir / "bindings.json"
        self.sync_buf_path = self.state_dir / "sync_buf.txt"
        self.context_tokens_path = self.state_dir / "context_tokens.json"
        self.media_temp_dir = self.state_dir / "tmp"

        self._client: httpx.AsyncClient | None = None
        self._poll_task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._credentials: dict[str, str] | None = None

        self._message_handler: Optional[Callable[[UnifiedContext], Any]] = None
        self._command_handlers: Dict[str, Callable[[UnifiedContext], Any]] = {}
        self._callback_handlers: List[
            Tuple[re.Pattern, Callable[[UnifiedContext], Any]]
        ] = []
        self._user_data_store: Dict[str, Dict[str, Any]] = {}
        self._context_tokens = self._load_context_tokens()
        self._typing_ticket_cache: Dict[str, Tuple[str, float]] = {}
        self._typing_cancel_tasks: Dict[str, asyncio.Task] = {}
        self._binding_tasks: Dict[str, asyncio.Task] = {}
        self.debug_updates = bool(WEIXIN_DEBUG_UPDATES)

    @property
    def can_update_message(self) -> bool:
        return False

    @staticmethod
    def _normalize_base_url(value: str) -> str:
        rendered = str(value or DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL
        return rendered if rendered.endswith("/") else f"{rendered}/"

    @staticmethod
    def _safe_text(value: Any) -> str:
        return str(value or "").strip()

    @staticmethod
    def _random_wechat_uin() -> str:
        return base64.b64encode(str(randbits(32)).encode("utf-8")).decode("utf-8")

    def _build_headers(self, token: str) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "Authorization": f"Bearer {token}",
            "X-WECHAT-UIN": self._random_wechat_uin(),
        }

    def _load_json(self, path: Path) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except Exception:
            logger.warning("Weixin state file is invalid: %s", path, exc_info=True)
            return None

    def _write_json(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(f"{path.suffix}.tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(path)

    def _default_bindings_payload(self) -> dict[str, Any]:
        return {
            "version": 1,
            "session": {
                "token": "",
                "baseUrl": self.base_url,
                "cdnBaseUrl": self.cdn_base_url,
                "accountId": "",
                "updated_at": "",
            },
            "bound_users": {},
        }

    def _normalize_bound_users(self, payload: Any) -> dict[str, dict[str, str]]:
        if not isinstance(payload, dict):
            return {}
        rows: dict[str, dict[str, str]] = {}
        for raw_user_id, raw_item in payload.items():
            user_id = self._safe_text(raw_user_id)
            if not user_id or not isinstance(raw_item, dict):
                continue
            rows[user_id] = {
                "status": self._safe_text(raw_item.get("status") or "active") or "active",
                "source": self._safe_text(raw_item.get("source")),
                "bound_at": self._safe_text(raw_item.get("bound_at")),
                "bound_by": self._safe_text(raw_item.get("bound_by")),
            }
        return rows

    def _load_bindings(self) -> dict[str, Any]:
        payload = self._load_json(self.bindings_path)
        default = self._default_bindings_payload()
        if not isinstance(payload, dict):
            return default
        session = dict(default.get("session") or {})
        session.update(dict(payload.get("session") or {}))
        session["token"] = self._safe_text(session.get("token"))
        session["baseUrl"] = self._normalize_base_url(session.get("baseUrl") or self.base_url)
        session["cdnBaseUrl"] = normalize_cdn_base_url(
            session.get("cdnBaseUrl") or self.cdn_base_url
        )
        session["accountId"] = self._safe_text(session.get("accountId"))
        session["updated_at"] = self._safe_text(session.get("updated_at"))
        return {
            "version": 1,
            "session": session,
            "bound_users": self._normalize_bound_users(payload.get("bound_users") or {}),
        }

    def _load_credentials(self) -> dict[str, str] | None:
        payload = self._load_bindings()
        session = payload.get("session") or {}
        if not isinstance(payload, dict):
            return None
        token = self._safe_text(session.get("token"))
        if not token:
            return None
        normalized = {
            "token": token,
            "baseUrl": self._normalize_base_url(
                session.get("baseUrl") or self.base_url
            ),
            "cdnBaseUrl": normalize_cdn_base_url(
                session.get("cdnBaseUrl") or self.cdn_base_url
            ),
            "accountId": self._safe_text(session.get("accountId")),
        }
        return normalized

    @staticmethod
    def _now_iso() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    async def _persist_binding(
        self,
        payload: dict[str, Any],
        *,
        source: str,
        bound_by: str = "",
    ) -> dict[str, str]:
        token = self._safe_text(payload.get("bot_token"))
        if not token:
            raise MessageSendError("Weixin login succeeded but bot_token is missing.")

        bound_user_id = self._safe_text(payload.get("ilink_user_id"))
        bindings = self._load_bindings()
        bindings["session"] = {
            "token": token,
            "baseUrl": self._normalize_base_url(payload.get("baseurl") or self.base_url),
            "cdnBaseUrl": normalize_cdn_base_url(
                payload.get("cdn_baseurl") or self.cdn_base_url
            ),
            "accountId": self._safe_text(payload.get("ilink_bot_id")),
            "updated_at": self._now_iso(),
        }
        if bound_user_id:
            bound_users = self._normalize_bound_users(bindings.get("bound_users") or {})
            bound_users[bound_user_id] = {
                "status": "active",
                "source": self._safe_text(source),
                "bound_at": self._now_iso(),
                "bound_by": self._safe_text(bound_by),
            }
            bindings["bound_users"] = bound_users
        self._write_json(self.bindings_path, bindings)

        credentials = {
            "token": self._safe_text(bindings["session"].get("token")),
            "baseUrl": self._safe_text(bindings["session"].get("baseUrl")),
            "cdnBaseUrl": self._safe_text(bindings["session"].get("cdnBaseUrl")),
            "accountId": self._safe_text(bindings["session"].get("accountId")),
        }
        self._credentials = credentials
        self.base_url = self._normalize_base_url(credentials["baseUrl"] or self.base_url)
        self.cdn_base_url = normalize_cdn_base_url(
            credentials["cdnBaseUrl"] or self.cdn_base_url
        )

        if bound_user_id:
            from core.channel_user_store import channel_user_store
            from core.config import is_user_admin
            from core.state_store import add_allowed_user

            await add_allowed_user(
                bound_user_id,
                added_by=bound_by or bound_user_id,
                description=f"weixin:{self._safe_text(source) or 'bind'}",
            )
            if not is_user_admin(bound_user_id):
                channel_user_store.ensure_user(
                    platform="weixin",
                    platform_user_id=bound_user_id,
                )
        return {
            "user_id": bound_user_id,
            "account_id": credentials["accountId"],
            "base_url": credentials["baseUrl"],
            "cdn_base_url": credentials["cdnBaseUrl"],
        }

    def list_bound_users(self) -> list[dict[str, str]]:
        bindings = self._load_bindings()
        bound_users = self._normalize_bound_users(bindings.get("bound_users") or {})
        rows = [
            {"user_id": user_id, **dict(item or {})}
            for user_id, item in bound_users.items()
        ]
        rows.sort(key=lambda item: str(item.get("bound_at") or ""), reverse=True)
        return rows

    async def _watch_additional_binding(
        self,
        *,
        requester_user_id: str,
        qrcode_token: str,
    ) -> None:
        notification = ""
        try:
            payload = await self._poll_qr_until_confirmed(qrcode_token)
            result = await self._persist_binding(
                payload,
                source="wxbind_qr",
                bound_by=requester_user_id,
            )
            bound_user_id = self._safe_text(result.get("user_id"))
            if bound_user_id:
                notification = (
                    f"✅ 微信绑定完成：`{bound_user_id}` 已加入 allow-list。"
                )
            else:
                notification = "✅ 微信绑定完成，但未拿到扫码用户 ID。"
        except Exception as exc:
            notification = f"❌ 绑定二维码已失效或绑定失败：{exc}"
        finally:
            self._binding_tasks.pop(self._safe_text(qrcode_token), None)

        with contextlib.suppress(Exception):
            await self.send_message(requester_user_id, notification)

    async def start_additional_binding(self, *, requester_user_id: str) -> dict[str, str]:
        qrcode_token, qr_url = await self._fetch_login_qr()
        existing = self._binding_tasks.pop(qrcode_token, None)
        if existing is not None:
            existing.cancel()
        self._binding_tasks[qrcode_token] = asyncio.create_task(
            self._watch_additional_binding(
                requester_user_id=self._safe_text(requester_user_id),
                qrcode_token=qrcode_token,
            ),
            name=f"weixin-bind-{qrcode_token}",
        )
        return {
            "qrcode_token": qrcode_token,
            "qr_content": qr_url,
            "qr_url": qr_url,
        }

    def _load_context_tokens(self) -> dict[str, str]:
        payload = self._load_json(self.context_tokens_path)
        if not isinstance(payload, dict):
            return {}
        rendered: dict[str, str] = {}
        for key, value in payload.items():
            user_id = self._safe_text(key)
            token = self._safe_text(value)
            if user_id and token:
                rendered[user_id] = token
        return rendered

    def _save_context_tokens(self) -> None:
        self._write_json(self.context_tokens_path, self._context_tokens)

    def _remember_context_token(self, user_id: str, context_token: str) -> None:
        safe_user_id = self._safe_text(user_id)
        safe_token = self._safe_text(context_token)
        if not safe_user_id or not safe_token:
            return
        if self._context_tokens.get(safe_user_id) == safe_token:
            return
        self._context_tokens[safe_user_id] = safe_token
        self._save_context_tokens()

    def _get_cached_typing_ticket(self, user_id: str) -> str:
        safe_user_id = self._safe_text(user_id)
        if not safe_user_id:
            return ""
        cached = self._typing_ticket_cache.get(safe_user_id)
        if not cached:
            return ""
        ticket, expires_at = cached
        if expires_at <= time.time():
            self._typing_ticket_cache.pop(safe_user_id, None)
            return ""
        return ticket

    async def _get_typing_ticket(self, user_id: str, context_token: str = "") -> str:
        safe_user_id = self._safe_text(user_id)
        if not safe_user_id:
            return ""

        cached = self._get_cached_typing_ticket(safe_user_id)
        if cached:
            return cached

        payload = {"ilink_user_id": safe_user_id}
        safe_context_token = self._safe_text(context_token)
        if safe_context_token:
            payload["context_token"] = safe_context_token
        payload["base_info"] = {"channel_version": "0.1.0"}

        response = await self._api_post("ilink/bot/getconfig", payload, timeout=10.0)
        ret = response.get("ret")
        if ret not in (None, 0):
            logger.warning(
                "Weixin getconfig failed ret=%s errmsg=%s user_id=%s",
                ret,
                self._safe_text(response.get("errmsg")),
                safe_user_id,
            )
            return ""

        ticket = self._safe_text(response.get("typing_ticket"))
        if ticket:
            self._typing_ticket_cache[safe_user_id] = (
                ticket,
                time.time() + DEFAULT_TYPING_CACHE_TTL_SEC,
            )
        return ticket

    async def _send_typing_status(
        self,
        *,
        user_id: str,
        status: int,
        context_token: str = "",
    ) -> bool:
        safe_user_id = self._safe_text(user_id)
        if not safe_user_id:
            return False

        ticket = await self._get_typing_ticket(
            safe_user_id,
            context_token=context_token,
        )
        if not ticket:
            return False

        response = await self._api_post(
            "ilink/bot/sendtyping",
            {
                "ilink_user_id": safe_user_id,
                "typing_ticket": ticket,
                "status": int(status or WEIXIN_TYPING_STATUS_TYPING),
                "base_info": {"channel_version": "0.1.0"},
            },
            timeout=10.0,
        )
        ret = response.get("ret")
        if ret not in (None, 0):
            logger.warning(
                "Weixin sendtyping failed ret=%s errmsg=%s user_id=%s status=%s",
                ret,
                self._safe_text(response.get("errmsg")),
                safe_user_id,
                status,
            )
            return False
        return True

    async def _cancel_typing_later(
        self,
        *,
        user_id: str,
        context_token: str = "",
        delay_sec: int = DEFAULT_TYPING_CANCEL_DELAY_SEC,
    ) -> None:
        try:
            await asyncio.sleep(
                max(1, int(delay_sec or DEFAULT_TYPING_CANCEL_DELAY_SEC))
            )
            await self._send_typing_status(
                user_id=user_id,
                status=WEIXIN_TYPING_STATUS_CANCEL,
                context_token=context_token,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "Weixin delayed typing cancel failed for user_id=%s",
                self._safe_text(user_id) or "-",
                exc_info=True,
            )
        finally:
            current = asyncio.current_task()
            if (
                current is not None
                and self._typing_cancel_tasks.get(self._safe_text(user_id)) is current
            ):
                self._typing_cancel_tasks.pop(self._safe_text(user_id), None)

    def _reschedule_typing_cancel(self, user_id: str, context_token: str = "") -> None:
        safe_user_id = self._safe_text(user_id)
        if not safe_user_id:
            return
        existing = self._typing_cancel_tasks.pop(safe_user_id, None)
        if existing is not None:
            existing.cancel()
        self._typing_cancel_tasks[safe_user_id] = asyncio.create_task(
            self._cancel_typing_later(
                user_id=safe_user_id,
                context_token=context_token,
            ),
            name=f"weixin-typing-cancel-{safe_user_id}",
        )

    def _load_sync_cursor(self) -> str:
        try:
            return self.sync_buf_path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return ""
        except Exception:
            logger.warning("Failed to load Weixin sync cursor.", exc_info=True)
            return ""

    def _save_sync_cursor(self, cursor: str) -> None:
        self.sync_buf_path.parent.mkdir(parents=True, exist_ok=True)
        self.sync_buf_path.write_text(str(cursor or "").strip(), encoding="utf-8")

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                follow_redirects=True,
                timeout=httpx.Timeout(35.0, connect=10.0),
            )
        return self._client

    async def _close_client(self) -> None:
        if self._client is None:
            return
        await self._client.aclose()
        self._client = None

    async def _api_post(
        self,
        endpoint: str,
        payload: dict[str, Any],
        *,
        timeout: float,
        token: str | None = None,
    ) -> dict[str, Any]:
        client = await self._ensure_client()
        auth_token = self._safe_text(token or (self._credentials or {}).get("token"))
        if not auth_token:
            raise MessageSendError("Weixin credentials are not available.")
        url = f"{self.base_url}{endpoint.lstrip('/')}"
        response = await client.post(
            url,
            json=payload,
            headers=self._build_headers(auth_token),
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise MessageSendError(f"Unexpected Weixin response from {endpoint}")
        return data

    async def _fetch_login_qr(self) -> tuple[str, str]:
        client = await self._ensure_client()
        url = f"{self.base_url}ilink/bot/get_bot_qrcode?bot_type=3"
        response = await client.get(url, timeout=30.0)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise MessageSendError("Unexpected Weixin QR response payload.")
        qrcode_token = self._safe_text(payload.get("qrcode"))
        qr_url = self._safe_text(payload.get("qrcode_img_content"))
        if not qrcode_token or not qr_url:
            raise MessageSendError(
                "Weixin QR response is missing qrcode or qrcode_img_content."
            )
        return qrcode_token, qr_url

    async def _fetch_qr_status(self, qrcode_token: str) -> dict[str, Any]:
        client = await self._ensure_client()
        url = str(
            httpx.URL(f"{self.base_url}ilink/bot/get_qrcode_status").copy_merge_params(
                {"qrcode": qrcode_token}
            )
        )
        response = await client.get(url, timeout=35.0)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise MessageSendError("Unexpected Weixin QR status payload.")
        return payload

    @staticmethod
    def _resolve_local_path(value: str) -> Path:
        rendered = str(value or "").strip()
        if rendered.startswith("file://"):
            parsed = urlparse(rendered)
            return Path(unquote(parsed.path)).expanduser().resolve()
        return Path(rendered).expanduser().resolve()

    async def _prepare_media_path(
        self,
        media: Union[str, bytes],
        *,
        filename: str | None,
        fallback_mime_type: str,
    ) -> tuple[Path, bool, str]:
        if isinstance(media, bytes):
            suffix = default_suffix_for_mime(fallback_mime_type)
            safe_name = self._safe_text(filename) or f"weixin-media{suffix}"
            target = self.media_temp_dir / f"{token_hex(4)}-{Path(safe_name).name}"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(media)
            return target, True, Path(safe_name).name

        candidate = self._safe_text(media)
        if not candidate:
            raise MessageSendError("Weixin media payload is empty.")

        if candidate.startswith(("http://", "https://")):
            client = await self._ensure_client()
            try:
                response = await client.get(candidate, timeout=60.0)
                response.raise_for_status()
            except Exception as exc:
                raise MessageSendError(f"Weixin media download failed: {exc}") from exc

            content = response.content
            if len(content) > WEIXIN_MEDIA_MAX_BYTES:
                raise MessageSendError(
                    "Weixin media is too large to upload via the current adapter."
                )

            hinted_name = self._safe_text(filename)
            suffix = (
                Path(hinted_name).suffix
                if hinted_name
                else extension_from_content_type_or_url(
                    response.headers.get("Content-Type"), candidate
                )
            )
            if not suffix:
                suffix = default_suffix_for_mime(fallback_mime_type)
            safe_name = hinted_name or f"weixin-remote{suffix}"
            target = self.media_temp_dir / f"{token_hex(4)}-{Path(safe_name).name}"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            return target, True, Path(safe_name).name

        resolved = self._resolve_local_path(candidate)
        if not resolved.exists() or not resolved.is_file():
            raise MessageSendError(f"Weixin media file does not exist: {resolved}")
        if resolved.stat().st_size > WEIXIN_MEDIA_MAX_BYTES:
            raise MessageSendError(
                "Weixin media is too large to upload via the current adapter."
            )
        return resolved, False, resolved.name

    async def _upload_media_file(
        self,
        *,
        file_path: Path,
        user_id: str,
        media_kind: str,
    ) -> UploadedWeixinMedia:
        plaintext = file_path.read_bytes()
        if len(plaintext) > WEIXIN_MEDIA_MAX_BYTES:
            raise MessageSendError(
                "Weixin media is too large to upload via the current adapter."
            )

        raw_size = len(plaintext)
        ciphertext_size = aes_ecb_padded_size(raw_size)
        raw_file_md5 = hashlib.md5(plaintext).hexdigest()
        aes_key = urandom(16)
        aes_key_hex = aes_key.hex()
        filekey = token_hex(16)
        upload_payload = {
            "filekey": filekey,
            "media_type": upload_media_type_for_kind(media_kind),
            "to_user_id": user_id,
            "rawsize": raw_size,
            "rawfilemd5": raw_file_md5,
            "filesize": ciphertext_size,
            "no_need_thumb": True,
            "aeskey": aes_key_hex,
            "base_info": {"channel_version": "0.1.0"},
        }
        response = await self._api_post(
            "ilink/bot/getuploadurl", upload_payload, timeout=15.0
        )
        upload_param = self._safe_text(response.get("upload_param"))
        if not upload_param:
            raise MessageSendError("Weixin getuploadurl did not return upload_param.")

        ciphertext = encrypt_aes_ecb(plaintext, aes_key)
        download_param = await self._upload_ciphertext_to_cdn(
            ciphertext=ciphertext,
            upload_param=upload_param,
            filekey=filekey,
        )
        return UploadedWeixinMedia(
            filekey=filekey,
            download_encrypted_query_param=download_param,
            aes_key_hex=aes_key_hex,
            plaintext_size=raw_size,
            ciphertext_size=ciphertext_size,
        )

    async def _upload_ciphertext_to_cdn(
        self,
        *,
        ciphertext: bytes,
        upload_param: str,
        filekey: str,
    ) -> str:
        client = await self._ensure_client()
        cdn_url = build_cdn_upload_url(self.cdn_base_url, upload_param, filekey)
        last_error: Exception | None = None

        for attempt in range(1, 4):
            try:
                response = await client.post(
                    cdn_url,
                    content=ciphertext,
                    headers={"Content-Type": "application/octet-stream"},
                    timeout=120.0,
                )
                if 400 <= response.status_code < 500:
                    body = response.headers.get("x-error-message") or response.text
                    raise MessageSendError(
                        f"Weixin CDN upload client error {response.status_code}: {body}"
                    )
                if response.status_code != 200:
                    body = (
                        response.headers.get("x-error-message")
                        or response.text
                        or f"status {response.status_code}"
                    )
                    raise RuntimeError(
                        f"Weixin CDN upload server error {response.status_code}: {body}"
                    )
                download_param = self._safe_text(
                    response.headers.get("x-encrypted-param")
                )
                if not download_param:
                    raise RuntimeError(
                        "Weixin CDN upload response missing x-encrypted-param."
                    )
                return download_param
            except MessageSendError:
                raise
            except Exception as exc:
                last_error = exc
                if attempt >= 3:
                    break
                logger.warning(
                    "Weixin CDN upload attempt %s failed, retrying: %s",
                    attempt,
                    exc,
                )

        raise MessageSendError(
            f"Weixin CDN upload failed: {last_error or 'unknown error'}"
        )

    async def _send_media_item_to_user(
        self,
        *,
        user_id: str,
        context_token: str,
        media_item: dict[str, Any],
        caption: str = "",
    ) -> SimpleNamespace:
        rendered_caption = markdown_to_weixin_text(caption)
        for chunk in self._chunk_text(rendered_caption, self.text_chunk_limit):
            await self._send_text_to_user(user_id, chunk, context_token)

        client_id = self._build_client_id()
        payload = {
            "msg": {
                "from_user_id": "",
                "to_user_id": user_id,
                "client_id": client_id,
                "message_type": 2,
                "message_state": 2,
                "item_list": [media_item],
                "context_token": context_token,
            },
            "base_info": {"channel_version": "0.1.0"},
        }
        response = await self._api_post("ilink/bot/sendmessage", payload, timeout=15.0)
        ret = response.get("ret")
        if ret not in (None, 0):
            raise MessageSendError(
                f"Weixin media send failed ret={ret} errmsg={self._safe_text(response.get('errmsg'))}"
            )
        return SimpleNamespace(id=client_id)

    async def _send_prepared_media(
        self,
        context: UnifiedContext,
        *,
        media: Union[str, bytes],
        caption: str | None,
        filename: str | None,
        fallback_mime_type: str,
    ) -> Any:
        user_id = self._safe_text(context.message.user.id)
        context_token = self._resolve_context_token(context=context, user_id=user_id)
        if not context_token:
            raise MessageSendError(
                "Weixin media reply requires a context_token from a recent inbound message."
            )

        prepared_path: Path | None = None
        should_cleanup = False
        display_name = ""
        try:
            prepared_path, should_cleanup, display_name = (
                await self._prepare_media_path(
                    media,
                    filename=filename,
                    fallback_mime_type=fallback_mime_type,
                )
            )
            mime_type = guess_mime_type(prepared_path.name)
            if mime_type == "application/octet-stream":
                mime_type = fallback_mime_type
            media_kind = classify_media_kind(mime_type)
            uploaded = await self._upload_media_file(
                file_path=prepared_path,
                user_id=user_id,
                media_kind=media_kind,
            )
            if media_kind == "image":
                message_item = build_image_message_item(uploaded)
            elif media_kind == "video":
                message_item = build_video_message_item(uploaded)
            else:
                message_item = build_file_message_item(
                    uploaded, display_name or prepared_path.name
                )

            return await self._send_media_item_to_user(
                user_id=user_id,
                context_token=context_token,
                media_item=message_item,
                caption=caption or "",
            )
        finally:
            if should_cleanup and prepared_path is not None:
                with contextlib.suppress(FileNotFoundError):
                    prepared_path.unlink()

    @staticmethod
    def _render_qr_ascii(data: str) -> str:
        try:
            import qrcode
        except Exception:
            return ""

        try:
            qr = qrcode.QRCode(border=1, box_size=1)
            qr.add_data(data)
            qr.make(fit=True)
            matrix = qr.get_matrix()
        except Exception:
            logger.warning("Failed to render Weixin QR in terminal.", exc_info=True)
            return ""

        lines = []
        for row in matrix:
            line = "".join("██" if cell else "  " for cell in row)
            lines.append(line.rstrip())
        return "\n".join(lines)

    @staticmethod
    def _png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
        chunk = bytes(chunk_type or b"") + bytes(payload or b"")
        return (
            struct.pack(">I", len(payload))
            + chunk
            + struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF)
        )

    @classmethod
    def _matrix_to_png_bytes(
        cls,
        matrix: list[list[bool]],
        *,
        scale: int = 8,
    ) -> bytes:
        rows = [list(row or []) for row in matrix if row]
        if not rows:
            return b""

        safe_scale = max(1, int(scale or 1))
        width_modules = len(rows[0])
        if width_modules <= 0:
            return b""

        expanded_width = width_modules * safe_scale
        image_rows = bytearray()
        for row in rows:
            if len(row) != width_modules:
                return b""
            expanded = bytearray()
            for cell in row:
                pixel = 0 if bool(cell) else 255
                expanded.extend([pixel] * safe_scale)
            expanded_bytes = bytes(expanded)
            for _ in range(safe_scale):
                image_rows.append(0)
                image_rows.extend(expanded_bytes)

        expanded_height = len(rows) * safe_scale
        ihdr = struct.pack(
            ">IIBBBBB",
            expanded_width,
            expanded_height,
            8,
            0,
            0,
            0,
            0,
        )
        compressed = zlib.compress(bytes(image_rows), level=9)
        return b"".join(
            [
                b"\x89PNG\r\n\x1a\n",
                cls._png_chunk(b"IHDR", ihdr),
                cls._png_chunk(b"IDAT", compressed),
                cls._png_chunk(b"IEND", b""),
            ]
        )

    @staticmethod
    def render_qr_png(data: str) -> bytes:
        safe_data = str(data or "").strip()
        if not safe_data:
            return b""
        try:
            import qrcode

            qr = qrcode.QRCode(border=4, box_size=8)
            qr.add_data(safe_data)
            qr.make(fit=True)
            return WeixinAdapter._matrix_to_png_bytes(qr.get_matrix(), scale=8)
        except Exception:
            logger.warning("Failed to render Weixin QR PNG.", exc_info=True)
            return b""

    async def _poll_qr_until_confirmed(self, qrcode_token: str) -> dict[str, Any]:
        deadline = asyncio.get_running_loop().time() + self.login_timeout_sec
        scan_notified = False

        while (
            asyncio.get_running_loop().time() < deadline
            and not self._stop_event.is_set()
        ):
            payload = await self._fetch_qr_status(qrcode_token)
            status = self._safe_text(payload.get("status")).lower()

            if status in {"", "wait"}:
                pass
            elif status == "scaned":
                if not scan_notified:
                    logger.info("Weixin QR has been scanned. Confirm login in WeChat.")
                    scan_notified = True
            elif status == "confirmed":
                return payload
            elif status in {"expired", "timeout"}:
                raise MessageSendError(f"Weixin QR login {status}.")
            else:
                logger.info("Weixin QR login status: %s", status)

            await asyncio.sleep(self.login_poll_interval_sec)

        raise MessageSendError("Weixin QR login timeout.")

    async def _ensure_credentials(self) -> None:
        existing = self._load_credentials()
        if existing:
            self._credentials = existing
            self.base_url = self._normalize_base_url(
                existing.get("baseUrl") or self.base_url
            )
            self.cdn_base_url = normalize_cdn_base_url(
                existing.get("cdnBaseUrl") or self.cdn_base_url
            )
            logger.info(
                "Weixin credentials loaded. base_url=%s cdn_base_url=%s account_id=%s",
                self.base_url,
                self.cdn_base_url,
                self._safe_text(existing.get("accountId")) or "-",
            )
            return

        while not self._stop_event.is_set():
            logger.warning(
                "Weixin bindings not found at %s. Starting QR login flow.",
                self.bindings_path,
            )
            qrcode_token, qr_url = await self._fetch_login_qr()
            qr_ascii = self._render_qr_ascii(qr_url)
            if qr_ascii:
                logger.info("Weixin QR login:\n%s", qr_ascii)
            logger.info("Open in WeChat if needed: %s", qr_url)

            try:
                payload = await self._poll_qr_until_confirmed(qrcode_token)
            except MessageSendError as exc:
                logger.warning("%s Requesting a new Weixin QR code...", exc)
                continue

            result = await self._persist_binding(
                payload,
                source="bootstrap_qr",
                bound_by=self._safe_text(payload.get("ilink_user_id")),
            )
            logger.info(
                "Weixin login confirmed. account_id=%s user_id=%s cdn_base_url=%s",
                self._safe_text(result.get("account_id")) or "-",
                self._safe_text(result.get("user_id")) or "-",
                self._safe_text(result.get("cdn_base_url")) or "-",
            )
            return

        raise MessageSendError("Weixin login aborted before credentials were obtained.")

    async def _get_updates(self, cursor: str) -> dict[str, Any]:
        try:
            return await self._api_post(
                "ilink/bot/getupdates",
                {
                    "get_updates_buf": cursor,
                    "base_info": {"channel_version": "0.1.0"},
                },
                timeout=35.0,
            )
        except httpx.ReadTimeout:
            return {
                "ret": 0,
                "msgs": [],
                "sync_buf": cursor,
                "get_updates_buf": cursor,
            }

    def _build_client_id(self) -> str:
        return f"x-bot-weixin-{int(time.time() * 1000)}-{token_hex(4)}"

    async def _send_text_to_user(
        self, user_id: str, text: str, context_token: str
    ) -> SimpleNamespace:
        client_id = self._build_client_id()
        payload = {
            "msg": {
                "from_user_id": "",
                "to_user_id": user_id,
                "client_id": client_id,
                "message_type": 2,
                "message_state": 2,
                "item_list": [{"type": 1, "text_item": {"text": text}}],
                "context_token": context_token,
            },
            "base_info": {"channel_version": "0.1.0"},
        }
        response = await self._api_post("ilink/bot/sendmessage", payload, timeout=15.0)
        ret = response.get("ret")
        if ret not in (None, 0):
            raise MessageSendError(
                f"Weixin sendmessage failed ret={ret} errmsg={self._safe_text(response.get('errmsg'))}"
            )
        return SimpleNamespace(id=client_id)

    @staticmethod
    def _chunk_text(text: str, limit: int) -> list[str]:
        rendered = str(text or "").strip()
        if not rendered:
            return []
        if len(rendered) <= limit:
            return [rendered]

        chunks: list[str] = []
        remaining = rendered
        while remaining:
            if len(remaining) <= limit:
                chunks.append(remaining)
                break
            cut = remaining.rfind("\n\n", 0, limit)
            if cut < int(limit * 0.6):
                cut = remaining.rfind("\n", 0, limit)
            if cut < int(limit * 0.4):
                cut = remaining.rfind(" ", 0, limit)
            if cut < int(limit * 0.3):
                cut = limit
            chunks.append(remaining[:cut].rstrip())
            remaining = remaining[cut:].lstrip()
        return [chunk for chunk in chunks if chunk]

    def _append_ui_hints(self, text: str, ui: Optional[Dict[str, Any]]) -> str:
        if not isinstance(ui, dict):
            return text
        actions = ui.get("actions")
        if not isinstance(actions, list) or not actions:
            return text

        hints: list[str] = []
        for row in actions:
            if not isinstance(row, list):
                continue
            for button in row:
                if not isinstance(button, dict):
                    continue
                label = self._safe_text(button.get("text")) or "操作"
                url = self._safe_text(button.get("url"))
                callback_data = self._safe_text(button.get("callback_data"))
                if url:
                    hints.append(f"- {label}: {url}")
                elif callback_data:
                    hints.append(f"- {label}: 回复 {CALLBACK_PREFIX}{callback_data}")
                else:
                    hints.append(f"- {label}")
                if len(hints) >= 6:
                    break
            if len(hints) >= 6:
                break

        if not hints:
            return text

        suffix = "\n".join(["", "可用操作：", *hints])
        return f"{text.rstrip()}{suffix}"

    def _resolve_context_token(
        self,
        *,
        context: UnifiedContext | None = None,
        user_id: str = "",
    ) -> str:
        candidate_user_id = self._safe_text(user_id)

        if context is not None:
            raw_data = getattr(context.message, "raw_data", {}) or {}
            if isinstance(raw_data, dict):
                token = self._safe_text(raw_data.get("context_token"))
                if token:
                    return token
                if not candidate_user_id:
                    candidate_user_id = self._safe_text(
                        raw_data.get("from_user_id") or raw_data.get("to_user_id")
                    )

            platform_event = getattr(context, "platform_event", None)
            if isinstance(platform_event, dict):
                token = self._safe_text(platform_event.get("context_token"))
                if token:
                    return token

            if not candidate_user_id:
                candidate_user_id = self._safe_text(
                    getattr(context.message.user, "id", "")
                )

        if candidate_user_id:
            return self._safe_text(self._context_tokens.get(candidate_user_id))
        return ""

    @staticmethod
    def _is_auto_reply_payload(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return True
        if isinstance(value, dict):
            return "text" in value
        return False

    async def _auto_reply_if_needed(
        self, unified_ctx: UnifiedContext, result: Any
    ) -> None:
        if not self._is_auto_reply_payload(result):
            return
        await unified_ctx.reply(result)

    async def _dispatch_command(self, ctx: UnifiedContext, text: str) -> bool:
        if not text.startswith("/"):
            return False
        command = text.split(" ", 1)[0][1:]
        handler = self._command_handlers.get(command)
        if handler is None:
            return False
        result = await handler(ctx)
        await self._auto_reply_if_needed(ctx, result)
        return True

    async def _dispatch_callback(self, ctx: UnifiedContext, text: str) -> bool:
        if not text.startswith(CALLBACK_PREFIX):
            return False
        callback_data = text[len(CALLBACK_PREFIX) :]
        if not callback_data:
            return False

        for pattern, handler in self._callback_handlers:
            if not pattern.search(callback_data):
                continue

            class CallbackUnifiedContext(UnifiedContext):
                @property
                def callback_data(self):
                    return self._cb_data

            callback_ctx = CallbackUnifiedContext(
                message=ctx.message,
                platform_event=ctx.platform_event,
                platform_ctx=ctx.platform_ctx,
                _adapter=self,
                user=ctx.user or ctx.message.user,
            )
            callback_ctx._cb_data = callback_data
            result = await handler(callback_ctx)
            await self._auto_reply_if_needed(callback_ctx, result)
            return True

        return False

    def _item_types_label(self, raw_message: dict[str, Any]) -> str:
        return (
            ",".join(
                str(item.get("type"))
                for item in (raw_message.get("item_list") or [])
                if isinstance(item, dict)
            )
            or "none"
        )

    def _log_updates_summary(self, payload: dict[str, Any]) -> None:
        if not self.debug_updates:
            return

        msgs = payload.get("msgs") or []
        sample = ""
        if msgs:
            first = msgs[0]
            if isinstance(first, dict):
                sample = json.dumps(first, ensure_ascii=False)[:1200]

        logger.info(
            "Weixin getupdates summary msg_count=%s sync_buf_len=%s get_updates_buf_len=%s sample=%s",
            len(msgs),
            len(self._safe_text(payload.get("sync_buf"))),
            len(self._safe_text(payload.get("get_updates_buf"))),
            sample or "-",
        )

    def _should_process_inbound_message(self, raw_message: dict[str, Any]) -> bool:
        if not any(
            isinstance(item, dict) for item in (raw_message.get("item_list") or [])
        ):
            return False
        message_type = raw_message.get("message_type")
        if message_type in (None, 1, "1"):
            return True

        from_user_id = self._safe_text(raw_message.get("from_user_id"))
        account_id = self._safe_text((self._credentials or {}).get("accountId"))
        if from_user_id and account_id and from_user_id == account_id:
            return False
        to_user_id = self._safe_text(raw_message.get("to_user_id"))
        if from_user_id:
            return True
        if not from_user_id and to_user_id:
            return False
        return False

    async def _handle_incoming_message(self, raw_message: dict[str, Any]) -> None:
        message_type = raw_message.get("message_type")
        item_types = self._item_types_label(raw_message)
        if not self._should_process_inbound_message(raw_message):
            logger.info(
                "Weixin inbound skipped from=%s to=%s message_type=%s item_types=%s",
                self._safe_text(raw_message.get("from_user_id")) or "-",
                self._safe_text(raw_message.get("to_user_id")) or "-",
                message_type,
                item_types,
            )
            return

        unified_msg = map_weixin_message(raw_message)
        logger.info(
            "Weixin inbound from=%s mapped_type=%s message_type=%s item_types=%s",
            unified_msg.user.id,
            unified_msg.type.value,
            message_type,
            item_types,
        )
        if message_type not in (None, 1, "1"):
            logger.info(
                "Weixin inbound accepted non-standard message_type=%s from=%s item_types=%s",
                message_type,
                unified_msg.user.id,
                item_types,
            )
        if (
            unified_msg.type.value == "text"
            and self._safe_text(unified_msg.text) == "(empty message)"
        ):
            logger.warning(
                "Weixin inbound could not be mapped to text/media. from=%s message_type=%s item_types=%s raw=%s",
                unified_msg.user.id,
                message_type,
                item_types,
                json.dumps(raw_message, ensure_ascii=False)[:1200],
            )
        context_token = self._safe_text(raw_message.get("context_token"))
        if context_token:
            self._remember_context_token(unified_msg.user.id, context_token)

        context = UnifiedContext(
            message=unified_msg,
            platform_ctx=self,
            platform_event=raw_message,
            _adapter=self,
            user=unified_msg.user,
        )

        text = self._safe_text(unified_msg.text)
        if text and await self._dispatch_command(context, text):
            return
        if text and await self._dispatch_callback(context, text):
            return

        if self._message_handler:
            result = await self._message_handler(context)
            await self._auto_reply_if_needed(context, result)

    @staticmethod
    def _iter_media_items(raw_message: dict[str, Any]) -> list[dict[str, Any]]:
        items = raw_message.get("item_list") or []
        rendered: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("type") in (2, 3, 4, 5):
                rendered.append(item)
        return rendered

    def _item_query_params(self, item: dict[str, Any]) -> list[str]:
        item_type = item.get("type")
        candidates: list[str] = []
        if item_type == 2:
            image_item = item.get("image_item") or {}
            for media_key in ("media", "thumb_media"):
                media = image_item.get(media_key) or {}
                query = self._safe_text(media.get("encrypt_query_param"))
                if query:
                    candidates.append(query)
        elif item_type == 3:
            voice_item = item.get("voice_item") or {}
            media = voice_item.get("media") or {}
            query = self._safe_text(media.get("encrypt_query_param"))
            if query:
                candidates.append(query)
        elif item_type == 4:
            file_item = item.get("file_item") or {}
            media = file_item.get("media") or {}
            query = self._safe_text(media.get("encrypt_query_param"))
            if query:
                candidates.append(query)
        elif item_type == 5:
            video_item = item.get("video_item") or {}
            for media_key in ("media", "thumb_media"):
                media = video_item.get(media_key) or {}
                query = self._safe_text(media.get("encrypt_query_param"))
                if query:
                    candidates.append(query)
        return candidates

    def _locate_media_item(
        self, raw_message: dict[str, Any], file_id: str
    ) -> dict[str, Any] | None:
        safe_file_id = self._safe_text(file_id)
        media_items = self._iter_media_items(raw_message)
        if not media_items:
            return None
        if safe_file_id:
            for item in media_items:
                if safe_file_id in self._item_query_params(item):
                    return item
        return media_items[0]

    def _resolve_media_download_query(self, item: dict[str, Any]) -> str:
        queries = self._item_query_params(item)
        return queries[0] if queries else ""

    def _resolve_media_download_key(self, item: dict[str, Any]) -> bytes | None:
        item_type = item.get("type")
        if item_type == 2:
            image_item = item.get("image_item") or {}
            raw_hex = self._safe_text(image_item.get("aeskey"))
            if raw_hex:
                try:
                    return bytes.fromhex(raw_hex)
                except ValueError:
                    logger.warning("Invalid Weixin image aeskey hex.")
            for media_key in ("media", "thumb_media"):
                media = image_item.get(media_key) or {}
                aes_key_b64 = self._safe_text(media.get("aes_key"))
                if aes_key_b64:
                    return parse_aes_key_base64(aes_key_b64)
            return None

        item_key = (
            "voice_item"
            if item_type == 3
            else "file_item" if item_type == 4 else "video_item"
        )
        payload = item.get(item_key) or {}
        for media_key in ("media", "thumb_media"):
            media = payload.get(media_key) or {}
            aes_key_b64 = self._safe_text(media.get("aes_key"))
            if aes_key_b64:
                return parse_aes_key_base64(aes_key_b64)
        return None

    async def _download_media_item(self, item: dict[str, Any]) -> bytes:
        encrypted_query_param = self._resolve_media_download_query(item)
        if not encrypted_query_param:
            raise MediaDownloadUnavailableError(
                "Weixin media item is missing encrypt_query_param."
            )

        client = await self._ensure_client()
        download_url = build_cdn_download_url(self.cdn_base_url, encrypted_query_param)
        try:
            response = await client.get(download_url, timeout=120.0)
            response.raise_for_status()
        except Exception as exc:
            raise MediaDownloadUnavailableError(
                f"Weixin CDN download failed: {exc}"
            ) from exc

        payload = bytes(response.content or b"")
        aes_key = None
        try:
            aes_key = self._resolve_media_download_key(item)
        except Exception as exc:
            raise MediaDownloadUnavailableError(
                f"Weixin media key parse failed: {exc}"
            ) from exc

        if not aes_key:
            return payload

        try:
            return decrypt_aes_ecb(payload, aes_key)
        except Exception as exc:
            raise MediaDownloadUnavailableError(
                f"Weixin media decrypt failed: {exc}"
            ) from exc

    async def _poll_loop(self) -> None:
        cursor = self._load_sync_cursor()
        failures = 0
        logger.info("Weixin long-poll started. base_url=%s", self.base_url)

        while not self._stop_event.is_set():
            try:
                payload = await self._get_updates(cursor)
                self._log_updates_summary(payload)
                ret = payload.get("ret")
                if ret not in (None, 0):
                    failures += 1
                    logger.warning(
                        "Weixin getupdates returned ret=%s errmsg=%s (%s/%s)",
                        ret,
                        self._safe_text(payload.get("errmsg")),
                        failures,
                        DEFAULT_MAX_FAILURES,
                    )
                    await asyncio.sleep(
                        DEFAULT_POLL_BACKOFF_SEC
                        if failures >= DEFAULT_MAX_FAILURES
                        else DEFAULT_POLL_RETRY_SEC
                    )
                    if failures >= DEFAULT_MAX_FAILURES:
                        failures = 0
                    continue

                failures = 0
                next_cursor = self._safe_text(payload.get("sync_buf")) or self._safe_text(
                    payload.get("get_updates_buf")
                )
                if next_cursor:
                    cursor = next_cursor
                    self._save_sync_cursor(cursor)

                for raw_message in payload.get("msgs") or []:
                    if not isinstance(raw_message, dict):
                        continue
                    try:
                        await self._handle_incoming_message(raw_message)
                    except Exception:
                        logger.error(
                            "Weixin inbound message handling failed.", exc_info=True
                        )
            except asyncio.CancelledError:
                raise
            except Exception:
                failures += 1
                logger.error(
                    "Weixin long-poll failed (%s/%s).",
                    failures,
                    DEFAULT_MAX_FAILURES,
                    exc_info=True,
                )
                await asyncio.sleep(
                    DEFAULT_POLL_BACKOFF_SEC
                    if failures >= DEFAULT_MAX_FAILURES
                    else DEFAULT_POLL_RETRY_SEC
                )
                if failures >= DEFAULT_MAX_FAILURES:
                    failures = 0

    async def start(self) -> None:
        self._stop_event.clear()
        await self._ensure_client()
        await self._ensure_credentials()
        if self._poll_task and not self._poll_task.done():
            return
        self._poll_task = asyncio.create_task(
            self._poll_loop(), name="weixin-long-poll"
        )

    async def stop(self) -> None:
        self._stop_event.set()
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._poll_task
        self._poll_task = None
        binding_tasks = list(self._binding_tasks.values())
        self._binding_tasks.clear()
        for task in binding_tasks:
            task.cancel()
        for task in binding_tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        typing_cancel_tasks = list(self._typing_cancel_tasks.values())
        self._typing_cancel_tasks.clear()
        for task in typing_cancel_tasks:
            task.cancel()
        for task in typing_cancel_tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await self._close_client()

    async def reply_text(
        self,
        context: UnifiedContext,
        text: str,
        ui: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Any:
        user_id = self._safe_text(context.message.user.id)
        context_token = self._resolve_context_token(context=context, user_id=user_id)
        if not context_token:
            raise MessageSendError(
                "Weixin reply requires a context_token from a recent inbound message."
            )

        rendered = markdown_to_weixin_text(text)
        rendered = self._append_ui_hints(rendered, ui)
        chunks = self._chunk_text(rendered, self.text_chunk_limit)
        if not chunks:
            return SimpleNamespace(id="")

        result: SimpleNamespace | None = None
        for chunk in chunks:
            result = await self._send_text_to_user(user_id, chunk, context_token)
        return result

    async def send_message(
        self,
        chat_id: Union[int, str],
        text: str,
        ui: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Any:
        user_id = self._safe_text(chat_id)
        context_token = self._resolve_context_token(user_id=user_id)
        if not context_token:
            raise MessageSendError(
                f"Weixin proactive send is unavailable for {user_id}: no cached context_token."
            )

        rendered = markdown_to_weixin_text(text)
        rendered = self._append_ui_hints(rendered, ui)
        chunks = self._chunk_text(rendered, self.text_chunk_limit)
        if not chunks:
            return SimpleNamespace(id="")

        result: SimpleNamespace | None = None
        for chunk in chunks:
            result = await self._send_text_to_user(user_id, chunk, context_token)
        return result

    async def edit_text(
        self,
        context: UnifiedContext,
        message_id: str,
        text: str,
        ui: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Any:
        logger.info(
            "Weixin does not support message editing; sending a new message instead."
        )
        return await self.reply_text(context, text, ui=ui, **kwargs)

    async def reply_photo(
        self,
        context: UnifiedContext,
        photo: Union[str, bytes],
        caption: Optional[str] = None,
        **kwargs,
    ) -> Any:
        return await self._send_prepared_media(
            context,
            media=photo,
            caption=caption,
            filename=kwargs.get("filename"),
            fallback_mime_type="image/jpeg",
        )

    async def reply_video(
        self,
        context: UnifiedContext,
        video: Union[str, bytes],
        caption: Optional[str] = None,
        **kwargs,
    ) -> Any:
        return await self._send_prepared_media(
            context,
            media=video,
            caption=caption,
            filename=kwargs.get("filename"),
            fallback_mime_type="video/mp4",
        )

    async def reply_audio(
        self,
        context: UnifiedContext,
        audio: Union[str, bytes],
        caption: Optional[str] = None,
        **kwargs,
    ) -> Any:
        if isinstance(audio, str) and audio.startswith(("http://", "https://")):
            text = (
                f"{caption or '音频链接'}\n{audio}" if caption else f"音频链接：{audio}"
            )
        else:
            text = caption or "⚠️ 当前微信通道暂不支持二进制音频上传。"
        return await self.reply_text(context, text)

    async def reply_document(
        self,
        context: UnifiedContext,
        document: Union[str, bytes],
        filename: Optional[str] = None,
        caption: Optional[str] = None,
        **kwargs,
    ) -> Any:
        return await self._send_prepared_media(
            context,
            media=document,
            caption=caption,
            filename=filename,
            fallback_mime_type="application/octet-stream",
        )

    async def delete_message(
        self,
        context: UnifiedContext,
        message_id: str,
        chat_id: Optional[str] = None,
        **kwargs,
    ) -> Any:
        logger.info("Weixin does not support message deletion.")
        return False

    async def send_chat_action(
        self,
        context: UnifiedContext,
        action: str,
        chat_id: Optional[str] = None,
        **kwargs,
    ) -> Any:
        safe_action = self._safe_text(action).lower()
        user_id = self._safe_text(chat_id or context.message.user.id)
        if not user_id:
            return None

        context_token = self._resolve_context_token(context=context, user_id=user_id)
        if safe_action in {"cancel", "cancel_typing", "typing_cancel", "stop"}:
            existing = self._typing_cancel_tasks.pop(user_id, None)
            if existing is not None:
                existing.cancel()
            try:
                await self._send_typing_status(
                    user_id=user_id,
                    status=WEIXIN_TYPING_STATUS_CANCEL,
                    context_token=context_token,
                )
            except Exception:
                logger.warning(
                    "Weixin typing cancel failed for user_id=%s",
                    user_id,
                    exc_info=True,
                )
            return None

        if safe_action not in {
            "typing",
            "record_audio",
            "record_voice",
            "upload_photo",
            "upload_video",
            "upload_document",
        }:
            return None

        try:
            sent = await self._send_typing_status(
                user_id=user_id,
                status=WEIXIN_TYPING_STATUS_TYPING,
                context_token=context_token,
            )
            if sent:
                self._reschedule_typing_cancel(user_id, context_token)
        except Exception:
            logger.warning(
                "Weixin send_chat_action failed action=%s user_id=%s",
                safe_action,
                user_id,
                exc_info=True,
            )
        return None

    async def download_file(
        self, context: UnifiedContext, file_id: str, **kwargs
    ) -> bytes:
        raw_message = getattr(context.message, "raw_data", None)
        if not isinstance(raw_message, dict):
            raise MediaDownloadUnavailableError(
                "Weixin media download requires raw inbound message payload."
            )

        item = self._locate_media_item(raw_message, file_id)
        if item is None:
            raise MediaDownloadUnavailableError(
                f"Weixin media item not found for file_id={self._safe_text(file_id)}."
            )

        return await self._download_media_item(item)

    def on_command(
        self,
        command: str,
        handler: Callable[[UnifiedContext], Any],
        description: str = None,
        **kwargs,
    ):
        self._command_handlers[command] = handler
        logger.info("Registered Weixin command: /%s", command)

    def on_message(self, filters_obj: Any, handler_func: Callable):
        self._message_handler = handler_func
        logger.info("Registered Weixin message handler")

    def register_message_handler(self, handler: Callable[[UnifiedContext], Any]):
        self._message_handler = handler
        logger.info("Registered Weixin message handler")

    def on_callback_query(self, pattern: str, handler: Callable[[UnifiedContext], Any]):
        compiled = re.compile(pattern)
        self._callback_handlers.append((compiled, handler))
        logger.info("Registered Weixin callback pattern: %s", pattern)

    def get_user_data(self, user_id: str) -> Dict[str, Any]:
        safe_user_id = self._safe_text(user_id)
        if safe_user_id not in self._user_data_store:
            self._user_data_store[safe_user_id] = {}
        return self._user_data_store[safe_user_id]
