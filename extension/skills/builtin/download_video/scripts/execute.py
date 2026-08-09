from __future__ import annotations

import argparse
import os
import asyncio
import logging
import sys
from pathlib import Path
from typing import Dict, Any

REPO_ROOT = Path(__file__).resolve().parents[5]
SRC_ROOT = REPO_ROOT / "src"
SCRIPT_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from core.file_artifacts import classify_file_kind
from core.platform.models import UnifiedContext
from core.skill_menu import make_callback, parse_callback
from core.config import (
    get_local_file_delivery_max_mb,
    is_user_admin,
    is_user_allowed,
)
from extension.skills.runtime_context import dispatch_context, notify_target
from utils import extract_video_url

if __package__:
    from .services.download_service import download_video, get_download_dir
    from .services.browser_login_service import (
        LOGIN_PROVIDERS,
        normalize_login_platform,
        run_browser_login,
    )
else:
    from services.download_service import download_video, get_download_dir
    from services.browser_login_service import (
        LOGIN_PROVIDERS,
        normalize_login_platform,
        run_browser_login,
    )

logger = logging.getLogger(__name__)
DOWNLOAD_MENU_NS = "dlm"


def _normalize_delivery_platform(value: Any) -> str:
    platform = str(value or "").strip().lower()
    return "weixin" if platform == "wechat" else platform


def _resolve_delivery_platform(
    ctx: UnifiedContext | None = None,
    params: dict[str, Any] | None = None,
    *,
    explicit: str = "",
) -> str:
    dispatch = dispatch_context(params)
    target = notify_target(ctx, params)
    message = getattr(ctx, "message", None)
    for candidate in (
        explicit,
        target.get("notify_platform"),
        dispatch.get("platform_name"),
        getattr(message, "platform", ""),
        os.getenv("X_BOT_RUNTIME_PLATFORM", ""),
    ):
        platform = _normalize_delivery_platform(candidate)
        if platform:
            return platform
    return ""


async def check_permission(ctx: UnifiedContext) -> bool:
    if not await is_user_allowed(ctx.message.user.id):
        return False
    return True


def _download_usage_text() -> str:
    return (
        "📹 **视频下载**\n\n"
        "直接发送以下命令：\n"
        "• `/download <视频链接>`\n"
        "• `/download video <视频链接>`\n"
        "• `/download audio <视频链接>`\n\n"
        "支持平台：X、YouTube、Instagram、TikTok、Bilibili、微博、抖音。\n"
        "需要登录时会自动发送二维码，也可用 `/login douyin` 主动登录。"
    )


def _download_menu_ui() -> dict:
    return {
        "actions": [
            [
                {"text": "📹 视频示例", "callback_data": make_callback(DOWNLOAD_MENU_NS, "videohelp")},
                {"text": "🎵 音频示例", "callback_data": make_callback(DOWNLOAD_MENU_NS, "audiohelp")},
            ]
        ]
    }


def _download_video_help() -> dict:
    return {
        "text": (
            "📹 **下载视频**\n\n"
            "直接发送：\n"
            "• `/download https://www.youtube.com/watch?v=xxx`\n"
            "• `/download video https://x.com/...`\n"
            "• `/download https://v.douyin.com/...`\n"
            "• `/download https://weibo.com/...`\n\n"
            "默认下载最佳可用视频。"
        ),
        "ui": {
            "actions": [
                [
                    {"text": "🎵 音频用法", "callback_data": make_callback(DOWNLOAD_MENU_NS, "audiohelp")},
                    {"text": "🏠 返回帮助", "callback_data": make_callback(DOWNLOAD_MENU_NS, "home")},
                ]
            ]
        },
    }


def _download_audio_help() -> dict:
    return {
        "text": (
            "🎵 **提取音频**\n\n"
            "直接发送：\n"
            "• `/download audio https://www.youtube.com/watch?v=xxx`\n\n"
            "这会优先返回 MP3 音频。"
        ),
        "ui": {
            "actions": [
                [
                    {"text": "📹 视频用法", "callback_data": make_callback(DOWNLOAD_MENU_NS, "videohelp")},
                    {"text": "🏠 返回帮助", "callback_data": make_callback(DOWNLOAD_MENU_NS, "home")},
                ]
            ]
        },
    }


def _parse_download_command(text: str) -> tuple[str, str]:
    raw = str(text or "").strip()
    if not raw:
        return "help", ""

    parts = raw.split(maxsplit=2)
    if not parts or not parts[0].startswith("/download"):
        return "help", ""
    if len(parts) == 1:
        return "help", ""

    sub = str(parts[1] or "").strip()
    lowered = sub.lower()
    if lowered in {"help", "h", "?"}:
        return "help", ""
    if lowered in {"audio", "mp3"}:
        return "audio", str(parts[2] if len(parts) >= 3 else "").strip()
    if lowered in {"video"}:
        return "video", str(parts[2] if len(parts) >= 3 else "").strip()
    return "video", " ".join(parts[1:]).strip()


def _parse_login_command(text: str) -> str | None:
    raw = str(text or "").strip()
    parts = raw.split(maxsplit=1)
    if len(parts) != 2 or not parts[0].startswith("/login"):
        return None
    return normalize_login_platform(parts[1])


def _login_usage_text() -> str:
    supported = "、".join(provider.display_name for provider in LOGIN_PROVIDERS.values())
    return (
        "📱 **扫码登录视频平台**\n\n"
        "用法：`/login <平台>`\n"
        "示例：`/login douyin`、`/login weibo`、`/login bilibili`\n\n"
        f"当前支持：{supported}。"
    )


# --- Skill Entry Point ---


async def execute(ctx: UnifiedContext, params: dict, runtime=None) -> Dict[str, Any]:
    """执行视频下载 (Stateless/AI called)"""
    url = params.get("url", "")
    format_type = params.get("format", "video")

    # Fallback: Try to extract URL from instruction if missing
    if not url and params.get("instruction"):
        import re

        match = re.search(r"(https?://[^\s]+)", params["instruction"])
        if match:
            url = match.group(0)

    if not url:
        return {"text": _download_usage_text(), "ui": _download_menu_ui()}

    return await process_video_download(
        ctx,
        url,
        audio_only=(format_type == "audio"),
        delivery_platform=_resolve_delivery_platform(ctx, params),
    )


async def download_command(ctx: UnifiedContext):
    """处理 /download 命令"""
    if not await check_permission(ctx):
        return None

    mode, raw_target = _parse_download_command(ctx.message.text or "")
    if mode == "help":
        return {"text": _download_usage_text(), "ui": _download_menu_ui()}

    url = extract_video_url(raw_target)
    if not url:
        return {
            "text": "❌ 未识别到有效视频链接。\n\n" + _download_usage_text(),
            "ui": _download_menu_ui(),
        }

    return await process_video_download(ctx, url, audio_only=(mode == "audio"))


async def login_command(ctx: UnifiedContext):
    if not await check_permission(ctx):
        return None
    user_id = ctx.message.user.id
    if not is_user_admin(user_id):
        return {"text": "⛔ 仅管理员可以建立平台登录会话。", "ui": {}}

    platform = _parse_login_command(ctx.message.text or "")
    if not platform:
        return {"text": _login_usage_text(), "ui": {}}

    provider = LOGIN_PROVIDERS[platform]
    progress = await ctx.reply(f"正在打开{provider.display_name}登录页，请稍候... ⏳")
    result = await run_browser_login(ctx, platform, user_id)
    await _delete_message_safely(ctx, progress)
    if result.success:
        return {
            "text": f"✅ {provider.display_name}登录成功，会话已安全保存。",
            "ui": {},
        }
    return {"text": f"❌ {result.error_message or '扫码登录失败。'}", "ui": {}}


def _build_download_file_payload(file_path: str, *, audio_only: bool = False) -> dict[str, str]:
    path = str(file_path or "").strip()
    filename = Path(path).name
    kind = "audio" if audio_only else classify_file_kind(filename)
    caption = "🎵 仅音频 (视频提取)" if audio_only else ""
    return {"path": path, "filename": filename, "kind": kind, "caption": caption}


async def _delete_message_safely(ctx: UnifiedContext, message: Any) -> None:
    msg_id = getattr(message, "message_id", getattr(message, "id", None))
    if not msg_id:
        return
    try:
        await ctx.delete_message(message_id=msg_id)
    except Exception:
        logger.debug("Failed to delete progress message", exc_info=True)


async def process_video_download(
    ctx: UnifiedContext,
    url: str,
    audio_only: bool = False,
    delivery_platform: str = "",
) -> Dict[str, Any]:
    """
    Core video download logic, shared by direct command and AI router.
    """
    user_id = ctx.message.user.id

    if not ctx.platform_ctx:
        logger.error("Platform context missing in process_video_download")
        return {"text": "❌ 下载失败：缺少平台上下文。", "ui": {}}

    format_text = "音频" if audio_only else "视频"
    delivery_platform = _resolve_delivery_platform(ctx, explicit=delivery_platform)

    processing_message = await ctx.reply(f"正在下载{format_text}，请稍候... ⏳")

    # 下载视频/音频
    result = await download_video(
        url,
        user_id,
        processing_message,
        audio_only=audio_only,
        delivery_platform=delivery_platform,
    )

    if (
        not result.success
        and getattr(result, "auth_required", False)
        and getattr(result, "auth_platform", None)
    ):
        if not is_user_admin(user_id):
            return {
                "text": "❌ 该平台需要登录，请联系管理员扫码建立登录会话。",
                "ui": {},
            }

        platform = str(result.auth_platform)
        provider = LOGIN_PROVIDERS.get(platform)
        if provider:
            progress_message_id = getattr(
                processing_message,
                "message_id",
                getattr(processing_message, "id", None),
            )
            if progress_message_id:
                await ctx.edit_message(
                    progress_message_id,
                    f"🔐 {provider.display_name}要求登录，正在生成二维码...",
                )
            login_result = await run_browser_login(ctx, platform, user_id)
            if login_result.success:
                if progress_message_id:
                    await ctx.edit_message(
                        progress_message_id,
                        "✅ 登录成功，正在自动重试下载...",
                    )
                result = await download_video(
                    url,
                    user_id,
                    processing_message,
                    audio_only=audio_only,
                    delivery_platform=delivery_platform,
                )
            else:
                return {
                    "text": f"❌ {login_result.error_message or '扫码登录失败。'}",
                    "ui": {},
                }

    if not result.success:
        if result.error_message:
            try:
                msg_id = getattr(
                    processing_message,
                    "message_id",
                    getattr(processing_message, "id", None),
                )
                if msg_id:
                    await ctx.edit_message(
                        msg_id, f"❌ 下载失败: {result.error_message}"
                    )
            except:
                pass
        return {"text": f"❌ 下载失败: {result.error_message or '未知错误'}", "ui": {}}

    file_path = result.file_path

    # 处理文件过大情况
    if result.is_too_large:
        max_file_size_mb = int(
            getattr(result, "max_file_size_mb", 0)
            or get_local_file_delivery_max_mb(delivery_platform)
        )
        platform_label = {
            "telegram": "Telegram",
            "weixin": "微信",
        }.get(delivery_platform, "当前")
        # 暂存路径到 user_data以供后续操作
        ctx.user_data["large_file_path"] = file_path
        ui = {
            "actions": [
                [
                    {"text": "🎵 仅发送音频", "callback_data": "large_file_audio"},
                ],
                [
                    {"text": "🗑️ 删除文件", "callback_data": "large_file_delete"},
                ],
            ]
        }

        msg_id = getattr(
            processing_message, "message_id", getattr(processing_message, "id", None)
        )
        if msg_id:
            await ctx.edit_message(
                msg_id,
                f"⚠️ **视频文件过大 ({result.file_size_mb:.1f}MB)**\n\n"
                f"超过{platform_label}渠道限制 ({max_file_size_mb}MB)，无法直接发送。\n"
                f"您可以选择：",
                ui=ui,
            )
        return {
            "text": (
                f"⚠️ **视频文件过大 ({result.file_size_mb:.1f}MB)**\n\n"
                f"超过{platform_label}渠道限制 ({max_file_size_mb}MB)，无法直接发送。\n"
                f"您可以选择："
            ),
            "ui": ui,
        }

    if not file_path or not os.path.exists(file_path):
        return {"text": "❌ 下载失败：未找到下载后的文件。", "ui": {}}

    logger.info("Downloaded to %s. Returning file payload for unified delivery.", file_path)

    # 记录统计。文件发送交给统一交付链路，skill 本身不直接 reply_audio/reply_video。
    from stats import increment_stat

    try:
        await increment_stat(user_id, "downloads")
    except Exception:
        logger.debug("Failed to increment download stats", exc_info=True)

    await _delete_message_safely(ctx, processing_message)
    return {
        "text": f"✅ {format_text}下载完成。",
        "files": [_build_download_file_payload(file_path, audio_only=audio_only)],
        "ui": {},
    }


async def handle_video_actions(ctx: UnifiedContext) -> None:
    """处理视频链接的下载操作"""
    logger.info(f"🎬 [DownloadVideo] Received callback action: {ctx.callback_data}")
    await ctx.answer_callback()
    logger.info(ctx.message)

    if not ctx.platform_ctx:
        logger.error("Platform context not found")
        return

    url = ctx.user_data.get("pending_video_url")
    if not url:
        try:
            await ctx.edit_message(ctx.message.id, "❌ 链接已过期，请重新发送。")
        except:
            pass
        return

    action = ctx.callback_data
    if not action:
        return

    if action == "action_download_video":
        try:
            await ctx.edit_message(ctx.message.id, "📹 准备下载视频...")
        except Exception as e:
            logger.error(f"Error editing message in handle_video_actions: {e}")
            pass

        return await process_video_download(ctx, url, audio_only=False)


async def handle_large_file_action(ctx: UnifiedContext) -> Dict[str, Any] | None:
    """处理大文件操作的回调"""
    await ctx.answer_callback()

    # if not await check_permission(ctx):
    #     return

    data = ctx.callback_data
    file_path = ctx.user_data.get("large_file_path")

    if not file_path or not os.path.exists(file_path):
        try:
            await ctx.edit_message(
                ctx.message.id, "❌ 文件已过期或不存在，请重新下载。"
            )
        except:
            pass
        return

    chat_id = ctx.message.chat.id

    try:
        if data == "large_file_delete":
            try:
                os.remove(file_path)
            except:
                pass
            await ctx.edit_message(ctx.message.id, "🗑️ 文件已删除。")

        elif data == "large_file_audio":
            await ctx.edit_message(ctx.message.id, "🎵 正在提取音频并发送，请稍候...")
            base, ext = os.path.splitext(file_path)
            if ext.lower() == ".mp4":
                audio_path = f"{base}.mp3"
                if not os.path.exists(audio_path):
                    cmd = [
                        "ffmpeg",
                        "-i",
                        file_path,
                        "-vn",
                        "-acodec",
                        "libmp3lame",
                        "-q:a",
                        "4",
                        "-y",
                        audio_path,
                    ]
                    process = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    await process.wait()

                final_path = audio_path
            else:
                final_path = file_path

            if os.path.getsize(final_path) > 50 * 1024 * 1024:
                await ctx.edit_message(
                    ctx.message.id, "❌ 提取的音频也超过 50MB，无法发送。"
                )
            else:
                await _delete_message_safely(ctx, ctx.message)
                return {
                    "text": "✅ 音频提取完成。",
                    "files": [
                        {
                            **_build_download_file_payload(final_path, audio_only=True),
                            "caption": "🎵 仅音频 (从大视频提取)",
                        }
                    ],
                    "ui": {},
                }

    except Exception as e:
        logger.error(f"Error handling large file action: {e}")
        await ctx.reply(f"❌ 操作失败: {str(e)}")


async def handle_download_menu_callback(ctx: UnifiedContext):
    data = ctx.callback_data
    if not data:
        return

    action, _parts = parse_callback(data, DOWNLOAD_MENU_NS)
    if not action:
        return

    await ctx.answer_callback()
    if action == "home":
        payload = {"text": _download_usage_text(), "ui": _download_menu_ui()}
    elif action == "videohelp":
        payload = _download_video_help()
    elif action == "audiohelp":
        payload = _download_audio_help()
    else:
        payload = {"text": "❌ 未知操作。", "ui": _download_menu_ui()}

    await ctx.edit_message(ctx.message.id, payload["text"], ui=payload.get("ui"))


def register_handlers(adapter_manager: Any):
    """Register stateless /download command and callbacks"""
    adapter_manager.on_command("download", download_command, description="下载视频或音频")
    adapter_manager.on_command("login", login_command, description="扫码登录视频平台")
    adapter_manager.on_callback_query("^action_.*", handle_video_actions)
    adapter_manager.on_callback_query("^large_file_", handle_large_file_action)
    adapter_manager.on_callback_query("^dlm_", handle_download_menu_callback)


class _ConsoleProgressMessage:
    def __init__(self):
        self._last_text = ""

    async def edit_text(self, text: str):
        self._emit(text)

    async def edit(self, content: str | None = None, **_kwargs):
        self._emit(content or "")

    def _emit(self, text: str) -> None:
        payload = str(text or "").strip()
        if payload and payload != self._last_text:
            print(payload, file=sys.stderr)
            self._last_text = payload


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download video/audio into the project downloads directory.",
    )
    parser.add_argument("url", help="Media URL to download")
    parser.add_argument(
        "--format",
        choices=("video", "audio"),
        default="video",
        help="Output format. Default: video",
    )
    return parser


async def _run_cli() -> int:
    parser = _build_cli_parser()
    args = parser.parse_args()
    progress = _ConsoleProgressMessage()
    result = await download_video(
        str(args.url or "").strip(),
        user_id=0,
        progress_message=progress,
        audio_only=str(args.format or "video").strip().lower() == "audio",
        delivery_platform=_resolve_delivery_platform(),
    )
    if not result.success:
        print(result.error_message or "download failed", file=sys.stderr)
        return 1

    download_dir = get_download_dir()
    saved_path = str(result.file_path or "").strip()
    print(f"download_dir={download_dir}")
    if saved_path:
        print(f"saved_path={saved_path}")
    print(f"is_too_large={str(bool(result.is_too_large)).lower()}")
    if result.file_size_mb:
        print(f"file_size_mb={result.file_size_mb:.2f}")
    return 0


from core.extension_base import SkillExtension


class DownloadVideoSkillExtension(SkillExtension):
    name = "download_video_extension"
    skill_name = "download_video"

    def register(self, runtime) -> None:
        register_handlers(runtime.adapter_manager)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run_cli()))
