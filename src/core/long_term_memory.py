from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from typing import Any, Protocol

from core.extension_runtime import get_extension_runtime, init_extension_runtime
from core.markdown_memory_store import _norm_text, _now_iso, markdown_memory_store
from core.memory_config import get_memory_provider_name

logger = logging.getLogger(__name__)

MemoryItem = dict[str, Any]


class LongTermMemoryProvider(Protocol):
    async def initialize(self) -> None: ...

    async def list_user_items(self, user_id: str) -> list[MemoryItem]: ...

    async def add_user_items(
        self, user_id: str, items: list[MemoryItem]
    ) -> list[MemoryItem]: ...

    async def list_ikaros_items(self) -> list[MemoryItem]: ...

    async def add_ikaros_items(self, items: list[MemoryItem]) -> list[MemoryItem]: ...


class LongTermMemoryService:
    def __init__(self):
        self._provider: LongTermMemoryProvider | None = None
        self._provider_name = ""
        self._init_lock: asyncio.Lock | None = None
        self._initialized = False
        self._ikaros_snapshot_cache = ""

    async def initialize(self) -> None:
        if self._initialized:
            return
        if self._init_lock is None:
            self._init_lock = asyncio.Lock()
        async with self._init_lock:
            if self._initialized:
                return
            provider_name = get_memory_provider_name()
            provider = self._build_provider(provider_name)
            await provider.initialize()
            self._provider = provider
            self._provider_name = provider_name
            self._initialized = True
            if provider_name == "mem0":
                await self._refresh_ikaros_snapshot_cache()

    def get_provider_name(self) -> str:
        if self._provider_name:
            return self._provider_name
        return get_memory_provider_name()

    def _build_provider(self, provider_name: str) -> LongTermMemoryProvider:
        name = str(provider_name or "").strip().lower()
        if not name:
            raise RuntimeError("long-term memory provider is empty")

        runtime = None
        try:
            runtime = get_extension_runtime()
        except RuntimeError:
            runtime = None

        active_name = (
            str(runtime.get_active_memory_provider_name() or "").strip().lower()
            if runtime is not None
            else ""
        )
        if runtime is None or (active_name and active_name != name):
            from extension.memories.registry import memory_registry

            runtime = init_extension_runtime(
                scheduler=SimpleNamespace(add_job=lambda *args, **kwargs: None)
            )
            memory_registry.activate_extension(runtime)
        active_name = str(runtime.get_active_memory_provider_name() or "").strip().lower()
        if active_name and active_name != name:
            raise RuntimeError(
                f"active memory provider mismatch: requested={name} active={active_name}"
            )
        provider = runtime.get_active_memory_provider()
        if provider is None:
            raise RuntimeError(f"unknown long-term memory provider: {name}")
        return provider

    async def _get_provider(self) -> LongTermMemoryProvider:
        if not self._initialized:
            await self.initialize()
        if self._provider is None:
            raise RuntimeError("long-term memory provider is not initialized")
        return self._provider

    @staticmethod
    def _dedupe_items(items: list[MemoryItem], *, keep_day: bool = False) -> list[MemoryItem]:
        rows: list[MemoryItem] = []
        seen: set[str] = set()
        for item in items:
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            metadata = item.get("metadata") if isinstance(item, dict) else {}
            day = ""
            if keep_day and isinstance(metadata, dict):
                day = str(metadata.get("day") or "").strip()
            key = _norm_text(f"{day}:{text}" if day else text)
            if not key or key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "text": text,
                    "metadata": dict(metadata) if isinstance(metadata, dict) else {},
                    "created_at": str(item.get("created_at") or "").strip(),
                }
            )
        return rows

    @staticmethod
    def _truncate(text: str, *, max_chars: int, keep: str = "head") -> str:
        """Truncate text; keep='head' for durable lists, keep='tail' for append-only logs."""
        content = str(text or "").strip()
        if len(content) <= max_chars:
            return content
        if max_chars <= 0:
            return ""
        if str(keep or "head").strip().lower() == "tail":
            return content[-max_chars:]
        return content[:max_chars].rstrip()

    def _render_ikaros_snapshot(self, items: list[MemoryItem], *, max_chars: int) -> str:
        lines: list[str] = []
        for item in self._dedupe_items(items):
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            metadata = item.get("metadata") if isinstance(item, dict) else {}
            day = ""
            if isinstance(metadata, dict):
                day = str(metadata.get("day") or "").strip()
            if day:
                lines.append(f"- [{day}] {text}")
            else:
                lines.append(f"- {text}")
        # Experiences are append-only; prefer the most recent tail.
        return self._truncate(
            "\n".join(lines).strip(),
            max_chars=max_chars,
            keep="tail",
        )

    async def _refresh_ikaros_snapshot_cache(self) -> None:
        provider = await self._get_provider()
        items = await provider.list_ikaros_items()
        self._ikaros_snapshot_cache = self._render_ikaros_snapshot(
            items,
            max_chars=100000,
        )

    async def load_core_snapshot(
        self,
        user_id: str,
        *,
        max_chars: int = 1200,
        max_items: int = 16,
    ) -> str:
        """Always-on core facts for L1 context injection."""
        items = await self._list_user_items_for_tier(str(user_id), tier="core")
        if not items:
            # Legacy/empty-core fallback: take a small head of all durable facts.
            all_items = self._dedupe_items(
                await (await self._get_provider()).list_user_items(str(user_id))
            )
            items = all_items[: max(1, int(max_items))]
        else:
            items = items[: max(1, int(max_items))]
        lines = [
            f"- {str(item.get('text') or '').strip()}"
            for item in items
            if str(item.get("text") or "").strip()
        ]
        if not lines:
            return ""
        return self._truncate(
            "【核心记忆】\n" + "\n".join(lines),
            max_chars=max(0, int(max_chars)),
            keep="head",
        )

    async def load_user_snapshot(
        self,
        user_id: str,
        *,
        include_daily: bool = True,
        max_chars: int = 2400,
    ) -> str:
        from core.context_budget import join_budgeted_blocks

        provider = await self._get_provider()
        items = self._dedupe_items(await provider.list_user_items(str(user_id)))
        core_items: list[MemoryItem] = []
        archive_items: list[MemoryItem] = []
        for item in items:
            tier = str((item.get("metadata") or {}).get("tier") or "").strip().lower()
            if tier == "archive":
                archive_items.append(item)
            else:
                # Missing tier (e.g. mem0) counts as core-facing durable fact.
                core_items.append(item)

        blocks: list[str] = []
        if core_items:
            blocks.append(
                "【核心记忆】\n"
                + "\n".join(
                    f"- {str(item.get('text') or '').strip()}"
                    for item in core_items
                    if str(item.get("text") or "").strip()
                )
            )
        if archive_items:
            blocks.append(
                "【归档记忆】\n"
                + "\n".join(
                    f"- {str(item.get('text') or '').strip()}"
                    for item in archive_items
                    if str(item.get("text") or "").strip()
                )
            )

        if include_daily:
            today = date.today()
            for day in (today, today - timedelta(days=1)):
                daily_text = markdown_memory_store._read_text(
                    markdown_memory_store.daily_path(str(user_id), day)
                ).strip()
                if not daily_text:
                    continue
                lines = daily_text.splitlines()
                tail = "\n".join(lines[-20:]).strip()
                if tail:
                    blocks.append(f"【近期记忆（{day.isoformat()}）】\n{tail}")

        if not blocks:
            return ""
        return join_budgeted_blocks(
            blocks,
            max_chars=max(0, int(max_chars)),
            priority_first=True,
        )

    async def _list_user_items_for_tier(
        self, user_id: str, *, tier: str
    ) -> list[MemoryItem]:
        safe_tier = str(tier or "core").strip().lower() or "core"
        if self.get_provider_name() == "file":
            return self._dedupe_items(
                markdown_memory_store.list_user_items_by_tier_sync(
                    str(user_id),
                    tier=safe_tier,
                )
            )
        provider = await self._get_provider()
        items = self._dedupe_items(await provider.list_user_items(str(user_id)))
        filtered = [
            item
            for item in items
            if str((item.get("metadata") or {}).get("tier") or "core").lower()
            == safe_tier
        ]
        # Non-file providers often lack tier metadata; treat all as core.
        return filtered or (items if safe_tier == "core" else [])

    async def search_user_memory(
        self,
        user_id: str,
        query: str,
        *,
        limit: int = 5,
        include_daily: bool = True,
    ) -> list[dict[str, Any]]:
        from core.memory_search import rank_memory_candidates

        q = str(query or "").strip()
        if not q:
            return []
        candidates: list[dict[str, str]] = []
        provider = await self._get_provider()
        for item in self._dedupe_items(await provider.list_user_items(str(user_id))):
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            tier = str((item.get("metadata") or {}).get("tier") or "core").strip().lower()
            candidates.append(
                {
                    "text": text,
                    "source": "core" if tier == "core" else "archive",
                    "tier": tier or "core",
                }
            )
        if include_daily:
            today = date.today()
            for day in (today, today - timedelta(days=1)):
                daily_text = markdown_memory_store._read_text(
                    markdown_memory_store.daily_path(str(user_id), day)
                ).strip()
                if not daily_text:
                    continue
                for line in daily_text.splitlines()[-40:]:
                    stripped = line.strip()
                    if not stripped.startswith("- "):
                        continue
                    text = stripped[2:].strip()
                    if text:
                        candidates.append(
                            {
                                "text": text,
                                "source": f"daily:{day.isoformat()}",
                                "tier": "daily",
                            }
                        )
        hits = rank_memory_candidates(
            candidates,
            query=q,
            limit=max(1, int(limit)),
            min_score=1.0,
        )
        return [
            {
                "text": hit.text,
                "source": hit.source,
                "score": hit.score,
                "tier": hit.tier,
            }
            for hit in hits
        ]

    def render_retrieved_memory(
        self,
        hits: list[dict[str, Any]],
        *,
        max_chars: int = 900,
    ) -> str:
        if not hits:
            return ""
        lines = ["【相关记忆】", "与本轮问题可能相关的已存事实（仅供参考）："]
        for hit in hits:
            text = str(hit.get("text") or "").strip()
            if not text:
                continue
            source = str(hit.get("source") or "").strip()
            if source:
                lines.append(f"- ({source}) {text}")
            else:
                lines.append(f"- {text}")
        return self._truncate("\n".join(lines), max_chars=max(0, int(max_chars)), keep="head")

    async def remember_user(
        self,
        user_id: str,
        content: str,
        *,
        source: str = "chat",
        tier: str = "core",
    ) -> tuple[bool, str]:
        text = str(content or "").strip()
        if not text:
            return False, "内容为空"

        provider = await self._get_provider()
        existing_items = await provider.list_user_items(str(user_id))
        existing_norms = {
            _norm_text(str(item.get("text") or "").strip()) for item in existing_items
        }

        facts = await markdown_memory_store.extract_user_facts_ai(text)
        if not facts:
            facts = [text]
        new_facts = [item for item in facts if _norm_text(item) not in existing_norms]
        safe_tier = "core" if str(tier or "core").strip().lower() == "core" else "archive"

        if new_facts:
            await provider.add_user_items(
                str(user_id),
                [
                    {
                        "text": item,
                        "metadata": {"tier": safe_tier},
                        "created_at": "",
                    }
                    for item in new_facts
                ],
            )

        daily_path = markdown_memory_store.daily_path(str(user_id))
        daily_existing = markdown_memory_store._read_text(daily_path)
        header = f"# {date.today().isoformat()}\n\n"
        if not daily_existing.strip():
            daily_existing = header
        elif not daily_existing.endswith("\n"):
            daily_existing += "\n"

        stamp = datetime.now().strftime("%H:%M:%S")
        daily_line = f"- [{stamp}] source={source}: {text[:500]}"
        markdown_memory_store._write_text(
            daily_path,
            daily_existing.rstrip() + f"\n{daily_line}\n",
            actor="user",
            reason="append_daily_memory",
        )

        detail = "；".join((new_facts or facts)[:4])
        return True, detail

    async def forget_user(
        self,
        user_id: str,
        query: str,
        *,
        limit: int = 8,
    ) -> tuple[bool, str]:
        text = str(query or "").strip()
        if not text:
            return False, "内容为空"
        if self.get_provider_name() != "file":
            # Best-effort for non-file: search then no-op write path is unsupported.
            hits = await self.search_user_memory(str(user_id), text, limit=limit)
            if not hits:
                return False, "未找到匹配记忆"
            return (
                False,
                "当前记忆后端不支持删除；匹配到："
                + "；".join(str(item.get("text") or "") for item in hits[:4]),
            )
        removed = markdown_memory_store.remove_user_items_matching(
            str(user_id),
            text,
            limit=max(1, int(limit)),
        )
        if not removed:
            return False, "未找到匹配记忆"
        return True, "；".join(removed[:4])

    async def remember_user_facts(
        self,
        user_id: str,
        facts: list[str],
        *,
        source: str = "daily_rollup",
        tier: str = "archive",
    ) -> int:
        cleaned = markdown_memory_store._dedupe(
            [str(item or "").strip() for item in facts],
            limit=16,
        )
        if not cleaned:
            return 0

        provider = await self._get_provider()
        existing_items = await provider.list_user_items(str(user_id))
        existing_norms = {
            _norm_text(str(item.get("text") or "").strip()) for item in existing_items
        }
        added = [fact for fact in cleaned if _norm_text(fact) not in existing_norms]
        if not added:
            return 0

        safe_tier = "core" if str(tier or "archive").strip().lower() == "core" else "archive"
        await provider.add_user_items(
            str(user_id),
            [
                {"text": fact, "metadata": {"tier": safe_tier}, "created_at": ""}
                for fact in added
            ],
        )

        day_path = markdown_memory_store.daily_path(str(user_id))
        existing_daily = markdown_memory_store._read_text(day_path)
        if not existing_daily.strip():
            existing_daily = f"# {date.today().isoformat()}\n\n"
        line = (
            f"- [{datetime.now().strftime('%H:%M:%S')}] source={source}: "
            + "；".join(added[:6])
        )
        markdown_memory_store._write_text(
            day_path,
            existing_daily.rstrip() + f"\n{line}\n",
            actor="system",
            reason="daily_rollup_trace",
        )
        return len(added)

    def load_ikaros_snapshot(self, *, max_chars: int = 1600) -> str:
        provider_name = self.get_provider_name()
        if provider_name == "file":
            return self._render_ikaros_snapshot(
                markdown_memory_store.list_ikaros_items_sync(),
                max_chars=max_chars,
            )
        if not self._initialized:
            raise RuntimeError(
                f"long-term memory provider '{provider_name}' must be initialized before sync access"
            )
        return self._truncate(self._ikaros_snapshot_cache, max_chars=max_chars)

    async def add_ikaros_experiences(
        self,
        experiences: list[str],
        *,
        day: date,
        source_user_id: str,
    ) -> int:
        records = markdown_memory_store._dedupe(
            [str(item or "").strip() for item in experiences],
            limit=8,
        )
        if not records:
            return 0

        provider = await self._get_provider()
        existing_items = await provider.list_ikaros_items()
        existing_norms = {
            _norm_text(str(item.get("text") or "").strip()) for item in existing_items
        }
        added = [item for item in records if _norm_text(item) not in existing_norms]
        if not added:
            return 0

        await provider.add_ikaros_items(
            [
                {
                    "text": item,
                    "metadata": {"day": day.isoformat()},
                    "created_at": "",
                }
                for item in added
            ]
        )

        day_path = markdown_memory_store.ikaros_daily_path(day)
        daily_existing = markdown_memory_store._read_text(day_path)
        if not daily_existing.strip():
            daily_existing = f"# {day.isoformat()}\n\n"
        detail = f"- user={source_user_id}: " + "；".join(added[:5])
        markdown_memory_store._write_text(
            day_path,
            daily_existing.rstrip() + f"\n{detail}\n",
            actor="system",
            reason="daily_rollup_ikaros_daily",
        )

        if self.get_provider_name() == "mem0":
            await self._refresh_ikaros_snapshot_cache()
        return len(added)

    async def rollup_today_sessions(
        self,
        user_id: str,
        *,
        target_day: date | None = None,
    ) -> dict[str, Any]:
        day = target_day or date.today()
        marker = markdown_memory_store._rollup_marker_path(str(user_id), day)
        if marker.exists():
            return {"ok": True, "skipped": True, "reason": "already_rolled"}

        from core.state_store import get_day_session_transcripts

        transcripts = await get_day_session_transcripts(
            user_id=str(user_id),
            day=day,
            max_sessions=32,
            max_chars_per_session=5000,
        )

        extracted = await markdown_memory_store.extract_daily_rollup_ai(transcripts)
        user_facts = markdown_memory_store._dedupe(
            extracted.get("user_facts") or [],
            limit=6,
        )
        added_user_count = await self.remember_user_facts(
            str(user_id),
            user_facts,
            source="daily_session_rollup",
        )

        ikaros_experiences = markdown_memory_store._dedupe(
            extracted.get("ikaros_experiences") or [],
            limit=5,
        )
        added_ikaros_count = await self.add_ikaros_experiences(
            ikaros_experiences,
            day=day,
            source_user_id=str(user_id),
        )

        marker.parent.mkdir(parents=True, exist_ok=True)
        try:
            marker.write_text(
                (
                    f"rolled_at: {_now_iso()}\n"
                    f"user_memory_added: {added_user_count}\n"
                    f"ikaros_exp_added: {added_ikaros_count}\n"
                ),
                encoding="utf-8",
            )
        except Exception:
            pass

        return {
            "ok": True,
            "skipped": False,
            "user_memory_added": added_user_count,
            "ikaros_experience_added": added_ikaros_count,
            "sessions": len(transcripts),
        }


long_term_memory = LongTermMemoryService()
