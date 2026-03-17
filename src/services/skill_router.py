"""Skill routing utilities for narrowing per-turn skill scope."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Iterable

from core.config import get_client_for_model
from core.extension_router import ExtensionCandidate
from core.model_config import get_routing_model
from services.openai_adapter import generate_text

logger = logging.getLogger(__name__)

SKILL_ROUTER_TIMEOUT_SEC = 8.0


@dataclass
class SkillRoutingDecision:
    ok: bool
    candidate_skills: list[str]
    reason: str
    confidence: float
    raw: str = ""


def _normalize_skill_name(value: str) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    return raw.replace("-", "_")


def _render_dialog_window(messages: Iterable[dict[str, str]]) -> str:
    lines: list[str] = []
    for item in list(messages or [])[-10:]:
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "").strip()
        if role not in {"user", "assistant", "model"} or not content:
            continue
        label = "用户" if role == "user" else "助手"
        lines.append(f"{label}: {content}")
    return "\n".join(lines).strip()


def _render_skill_catalog(candidates: Iterable[ExtensionCandidate]) -> str:
    lines: list[str] = []
    for candidate in list(candidates or []):
        name = str(getattr(candidate, "name", "") or "").strip()
        if not name:
            continue
        description = str(getattr(candidate, "description", "") or "").strip()
        triggers = [
            str(item or "").strip()
            for item in list(getattr(candidate, "triggers", []) or [])[:8]
            if str(item or "").strip()
        ]
        line = f'- name: "{name}"'
        if description:
            line += f' | desc: "{description[:180]}"'
        if triggers:
            line += f' | triggers: "{", ".join(triggers[:6])}"'
        lines.append(line)
    return "\n".join(lines).strip()


class SkillRouter:
    async def route(
        self,
        *,
        dialog_messages: Iterable[dict[str, str]],
        candidates: Iterable[ExtensionCandidate],
        max_candidates: int = 5,
    ) -> SkillRoutingDecision:
        candidate_rows = [item for item in list(candidates or []) if getattr(item, "name", None)]
        if not candidate_rows:
            return SkillRoutingDecision(
                ok=True,
                candidate_skills=[],
                reason="no_candidates",
                confidence=1.0,
            )

        rendered_dialog = _render_dialog_window(dialog_messages)
        if not rendered_dialog:
            rendered_dialog = "用户尚未提供足够上下文，请根据当前技能目录做宽松判断。"
        rendered_catalog = _render_skill_catalog(candidate_rows)
        if not rendered_catalog:
            return SkillRoutingDecision(
                ok=True,
                candidate_skills=[],
                reason="empty_catalog",
                confidence=1.0,
            )

        prompt = (
            "你是技能路由器。请根据最近对话内容，宽松判断本轮可能会用到哪些技能。\n"
            "要求：\n"
            "1. 只从给定技能目录里选择。\n"
            "2. 倾向于多给一点候选，但不要瞎选完全无关的技能。\n"
            "3. 如果没有明显相关技能，返回空数组。\n"
            "4. 只返回 JSON，不要输出解释文本。\n"
            'JSON 格式：{"candidate_skills":["skill_a","skill_b"],"reason":"...","confidence":0-1}\n\n'
            f"最近对话：\n{rendered_dialog}\n\n"
            f"技能目录：\n{rendered_catalog}\n"
        )

        try:
            model_name = get_routing_model()
            client = get_client_for_model(model_name, is_async=True)
            if client is None:
                raise RuntimeError("OpenAI async client is not initialized")
            payload = await asyncio.wait_for(
                generate_text(
                    async_client=client,
                    model=model_name,
                    contents=prompt,
                    config={
                        "system_instruction": (
                            "你只负责技能候选缩圈。"
                            "不要回答用户问题，不要补充额外文本。"
                        ),
                        "temperature": 0,
                        "response_mime_type": "application/json",
                    },
                ),
                timeout=SKILL_ROUTER_TIMEOUT_SEC,
            )
            raw = str(payload or "").strip()
            parsed = self._parse_json(raw)
            reason = str(parsed.get("reason") or "").strip()[:240]
            try:
                confidence = max(0.0, min(1.0, float(parsed.get("confidence") or 0.0)))
            except Exception:
                confidence = 0.0
            selected = self._resolve_skills(
                parsed.get("candidate_skills"),
                candidate_rows,
                max_candidates=max_candidates,
            )
            return SkillRoutingDecision(
                ok=True,
                candidate_skills=selected,
                reason=reason or "ok",
                confidence=confidence,
                raw=raw[:800],
            )
        except Exception as exc:
            logger.debug("Skill router failed: %s", exc, exc_info=True)
            return SkillRoutingDecision(
                ok=False,
                candidate_skills=[],
                reason=f"router_error:{exc}",
                confidence=0.0,
            )

    @staticmethod
    def _resolve_skills(
        raw_skills: Any,
        candidates: list[ExtensionCandidate],
        *,
        max_candidates: int,
    ) -> list[str]:
        if not isinstance(raw_skills, list):
            return []
        by_exact = {
            str(item.name or "").strip(): str(item.name or "").strip()
            for item in candidates
            if str(item.name or "").strip()
        }
        by_normalized = {
            _normalize_skill_name(str(item.name or "").strip()): str(item.name or "").strip()
            for item in candidates
            if str(item.name or "").strip()
        }
        selected: list[str] = []
        for item in raw_skills:
            token = str(item or "").strip()
            if not token:
                continue
            resolved = by_exact.get(token) or by_normalized.get(_normalize_skill_name(token))
            if not resolved or resolved in selected:
                continue
            selected.append(resolved)
            if len(selected) >= max(1, int(max_candidates)):
                break
        return selected

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        text = str(raw or "").strip()
        if not text:
            raise ValueError("empty_response")
        try:
            loaded = json.loads(text)
            if isinstance(loaded, dict):
                return loaded
        except Exception:
            pass
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise ValueError("json_not_found")
        loaded = json.loads(match.group(0))
        if not isinstance(loaded, dict):
            raise ValueError("json_not_object")
        return loaded


skill_router = SkillRouter()
