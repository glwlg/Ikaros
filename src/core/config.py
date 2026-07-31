"""
配置模块 - 管理环境变量和常量
"""

import json
import os
import shlex

from dotenv import load_dotenv

from core.app_paths import data_dir, env_path, models_config_path, project_root

try:
    from openai import AsyncOpenAI, OpenAI  # type: ignore[reportMissingImports]
except Exception:  # pragma: no cover - optional during migration bootstrap
    AsyncOpenAI = None
    OpenAI = None

# 加载环境变量（如果 .env 文件存在）
# Docker 容器中通过 docker-compose 的 env_file 直接注入环境变量
load_dotenv(dotenv_path=env_path(), override=False)

# Telegram Bot 配置
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Discord Bot 配置
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# DingTalk (钉钉) Stream Mode 配置
DINGTALK_CLIENT_ID = os.getenv("DINGTALK_CLIENT_ID")
DINGTALK_CLIENT_SECRET = os.getenv("DINGTALK_CLIENT_SECRET")


def _env_int(name: str, default: int) -> int:
    try:
        return int(str(os.getenv(name, str(default))).strip())
    except Exception:
        return default


# Weixin (微信 iLink Bot) 配置
WEIXIN_BASE_URL = os.getenv("WEIXIN_BASE_URL", "https://ilinkai.weixin.qq.com/")
WEIXIN_CDN_BASE_URL = os.getenv(
    "WEIXIN_CDN_BASE_URL", "https://novac2c.cdn.weixin.qq.com/c2c"
)
WEIXIN_LOGIN_TIMEOUT_SEC = _env_int("WEIXIN_LOGIN_TIMEOUT_SEC", 300)
WEIXIN_LOGIN_POLL_INTERVAL_SEC = _env_int("WEIXIN_LOGIN_POLL_INTERVAL_SEC", 3)
WEIXIN_TEXT_CHUNK_LIMIT = _env_int("WEIXIN_TEXT_CHUNK_LIMIT", 2000)
WEIXIN_DEBUG_UPDATES = os.getenv("WEIXIN_DEBUG_UPDATES", "false").lower() == "true"
WEIXIN_SEND_VIDEO_AS_FILE = (
    os.getenv("WEIXIN_SEND_VIDEO_AS_FILE", "false").lower() == "true"
)
# Weixin cannot attach text+image in one bubble. Buffer nearby inbound messages
# from the same user and merge text into media caption before dispatch.
try:
    WEIXIN_INBOUND_MERGE_WINDOW_SEC = float(
        os.getenv("WEIXIN_INBOUND_MERGE_WINDOW_SEC", "3.0") or 3.0
    )
except Exception:
    WEIXIN_INBOUND_MERGE_WINDOW_SEC = 3.0

# 日志配置
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# 模型配置路径
MODELS_CONFIG_PATH = str(models_config_path())


# ============================================================================
# OpenAI Client 初始化 - 从 models.json 获取配置
# ============================================================================

_clients_cache = {}
_wrapped_clients_cache = {}


def get_client_for_model(
    model_key: str | None = None,
    is_async: bool = True,
    *,
    suppress_bearer_auth: bool = False,
):
    """获取指定模型对应的 OpenAI 客户端"""
    if OpenAI is None or AsyncOpenAI is None:
        return None

    # Importing here to avoid circular dependencies
    from core.model_config import (
        get_api_key_for_model,
        get_base_url_for_model,
        get_current_model,
        get_headers_for_model,
    )
    from core.llm_usage_store import wrap_openai_client

    key = model_key or get_current_model()
    api_key = get_api_key_for_model(key)
    base_url = get_base_url_for_model(key)
    headers = get_headers_for_model(key)

    if suppress_bearer_auth:
        headers = {
            name: value
            for name, value in headers.items()
            if name.lower() != "authorization"
        }
        headers["Authorization"] = ""

    if not api_key:
        return None

    headers_key = json.dumps(headers, ensure_ascii=False, sort_keys=True)
    cache_key = f"{api_key}:{base_url}:{headers_key}:{is_async}"
    if cache_key not in _clients_cache:
        client_kwargs = {
            "api_key": api_key,
            "base_url": base_url,
        }
        if headers:
            client_kwargs["default_headers"] = headers
        if is_async:
            _clients_cache[cache_key] = AsyncOpenAI(**client_kwargs)
        else:
            _clients_cache[cache_key] = OpenAI(**client_kwargs)

    wrapper_key = f"{cache_key}:{str(key or '').strip() or '__default__'}"
    if wrapper_key not in _wrapped_clients_cache:
        _wrapped_clients_cache[wrapper_key] = wrap_openai_client(
            _clients_cache[cache_key],
            default_model_key=str(key or "").strip(),
        )

    return _wrapped_clients_cache[wrapper_key]


# 为了兼容尚未迁移的旧代码，提供一个代理客户端
class AsyncOpenAIProxy:
    def __getattr__(self, name):
        client = get_client_for_model(None, True)
        if not client:
            raise RuntimeError("No client available for primary model")
        return getattr(client, name)


class SyncOpenAIProxy:
    def __getattr__(self, name):
        client = get_client_for_model(None, False)
        if not client:
            raise RuntimeError("No client available for primary model")
        return getattr(client, name)


openai_client = SyncOpenAIProxy() if OpenAI else None
openai_async_client = AsyncOpenAIProxy() if AsyncOpenAI else None


# ============================================================================
# 用户访问控制
# ============================================================================

ADMIN_USER_IDS_STR = os.getenv("ADMIN_USER_IDS", "")
ADMIN_USER_IDS = set()
if ADMIN_USER_IDS_STR.strip():
    ADMIN_USER_IDS = {
        uid.strip() for uid in ADMIN_USER_IDS_STR.split(",") if uid.strip()
    }


async def is_user_allowed(user_id: int | str) -> bool:
    """
    检查用户是否有权限使用 Bot。

    管理员仅来自 `ADMIN_USER_IDS`；
    普通可用用户来自持久化 allow-list。
    """
    uid_str = str(user_id).strip()
    if not uid_str:
        return False
    if uid_str in ADMIN_USER_IDS:
        return True
    try:
        from core.state_store import check_user_allowed_in_db

        return await check_user_allowed_in_db(uid_str)
    except Exception:
        return False


def is_user_admin(user_id: int | str) -> bool:
    """检查用户是否为管理员"""
    return str(user_id).strip() in ADMIN_USER_IDS


# ============================================================================
# 下载配置
# ============================================================================


DOWNLOAD_DIR = "downloads"
DATA_DIR = str(data_dir())
PERMANENT_STORAGE_DIR = "/app/media"  # For files > 49MB
UPDATE_INTERVAL_SECONDS = 2  # 进度更新间隔（秒）
MAX_FILE_SIZE_MB = 49  # Telegram 最大文件大小限制
COOKIES_FILE = os.path.join(DATA_DIR, "cookies.txt")  # yt-dlp cookies file path

# 会话状态常量
WAITING_FOR_VIDEO_URL = 1
WAITING_FOR_REMIND_INPUT = 3
WAITING_FOR_MONITOR_KEYWORD = 4
WAITING_FOR_SUBSCRIBE_URL = 5
WAITING_FOR_FEATURE_INPUT = 6

# External Search Service Provider ("searxng" is default)
SEARCH_PROVIDER = os.getenv("SEARCH_PROVIDER", "searxng")
SEARXNG_URL = os.getenv("SEARXNG_URL")

# Server IP Override (Optional, for fixed deployment)
SERVER_IP = os.getenv("SERVER_IP")

# Deployment Staging Path (Optional, for Docker deployment feature)
X_DEPLOYMENT_STAGING_PATH = os.getenv("X_DEPLOYMENT_STAGING_PATH")

# Heartbeat runtime configuration
HEARTBEAT_ENABLED = os.getenv("HEARTBEAT_ENABLED", "true").lower() == "true"
HEARTBEAT_EVERY = os.getenv("HEARTBEAT_EVERY", "30m")
HEARTBEAT_TARGET = os.getenv("HEARTBEAT_TARGET", "last")
HEARTBEAT_ACTIVE_START = os.getenv("HEARTBEAT_ACTIVE_START", "08:00")
HEARTBEAT_ACTIVE_END = os.getenv("HEARTBEAT_ACTIVE_END", "22:00")
HEARTBEAT_TIMEZONE = os.getenv("HEARTBEAT_TIMEZONE", "")
HEARTBEAT_TICK_SEC = int(os.getenv("HEARTBEAT_TICK_SEC", "30"))
HEARTBEAT_SUPPRESS_OK = os.getenv("HEARTBEAT_SUPPRESS_OK", "true").lower() == "true"
HEARTBEAT_MODE = os.getenv("HEARTBEAT_MODE", "readonly").strip().lower() or "readonly"


def _as_int(value: str, default: int) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return default


def _as_float(value: str, default: float) -> float:
    try:
        return float(str(value).strip())
    except Exception:
        return default


# Auto recovery budget for terminal/recoverable failures in orchestrator loop
AUTO_RECOVERY_MAX_ATTEMPTS = int(os.getenv("AUTO_RECOVERY_MAX_ATTEMPTS", "3"))

# Core chat execution policy:
# - ikaros_only: ikaros handles the request directly
# - ikaros_with_subagents: ikaros may launch internal subagents when needed
CORE_CHAT_EXECUTION_MODE = (
    os.getenv("CORE_CHAT_EXECUTION_MODE", "ikaros_with_subagents").strip().lower()
    or "ikaros_with_subagents"
)

# Replaceable Ikaros execution kernel. `native` keeps the historical
# AgentOrchestrator + AiService loop; `agents_sdk` uses OpenAI Agents SDK
# with Ikaros tools; `codex` delegates task execution to `codex app-server`
# from the Ikaros repo root.
IKAROS_KERNEL = os.getenv("IKAROS_KERNEL", "native").strip().lower() or "native"
IKAROS_CODEX_COMMAND = os.getenv("IKAROS_CODEX_COMMAND", "codex").strip() or "codex"
IKAROS_CODEX_ARGS = (
    os.getenv("IKAROS_CODEX_ARGS", "app-server --listen stdio://").strip()
    or "app-server --listen stdio://"
)
IKAROS_CODEX_MODEL = os.getenv("IKAROS_CODEX_MODEL", "").strip()
IKAROS_CODEX_EFFORT = os.getenv("IKAROS_CODEX_EFFORT", "").strip()
IKAROS_CODEX_SANDBOX = (
    os.getenv("IKAROS_CODEX_SANDBOX", "workspace-write").strip() or "workspace-write"
)
IKAROS_CODEX_APPROVAL_POLICY = (
    os.getenv("IKAROS_CODEX_APPROVAL_POLICY", "never").strip() or "never"
)
IKAROS_CODEX_WRITABLE_ROOTS = os.getenv("IKAROS_CODEX_WRITABLE_ROOTS", "").strip()
IKAROS_CODEX_SKILL_ALLOWLIST = os.getenv("IKAROS_CODEX_SKILL_ALLOWLIST", "").strip()
IKAROS_CODEX_SKILL_DENYLIST = os.getenv("IKAROS_CODEX_SKILL_DENYLIST", "").strip()
IKAROS_CODEX_TIMEOUT_SEC = _env_int("IKAROS_CODEX_TIMEOUT_SEC", 1800)
IKAROS_CODEX_REQUEST_TIMEOUT_SEC = _env_int("IKAROS_CODEX_REQUEST_TIMEOUT_SEC", 300)


def ikaros_kernel_provider() -> str:
    provider = (
        str(os.getenv("IKAROS_KERNEL", IKAROS_KERNEL) or "native").strip().lower()
    )
    return provider if provider in {"native", "agents_sdk", "codex"} else "native"


def ikaros_codex_command() -> list[str]:
    command = str(
        os.getenv("IKAROS_CODEX_COMMAND", IKAROS_CODEX_COMMAND) or "codex"
    ).strip()
    args = str(
        os.getenv("IKAROS_CODEX_ARGS", IKAROS_CODEX_ARGS)
        or "app-server --listen stdio://"
    ).strip()
    return [command, *shlex.split(args)] if command else shlex.split(args)


def ikaros_codex_writable_roots() -> list[str]:
    roots = [str(project_root().resolve())]
    raw = str(os.getenv("IKAROS_CODEX_WRITABLE_ROOTS", IKAROS_CODEX_WRITABLE_ROOTS) or "")
    for item in raw.split(os.pathsep):
        candidate = item.strip()
        if candidate:
            roots.append(candidate)
    return list(dict.fromkeys(roots))

# Kernel-protected source roots (comma-separated absolute/relative paths)
KERNEL_PROTECTED_PATHS = os.getenv("KERNEL_PROTECTED_PATHS", "")

# 确保目录存在
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)
