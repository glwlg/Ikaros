from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping


def _env_int(name: str, default: int, *, minimum: int = 0) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except Exception:
        value = default
    return max(minimum, value)


# Rough mixed-language estimate: ~4 chars per token for Latin, closer to 1.5–2 for CJK.
# Phase A keeps a simple stable estimator (no tokenizer dependency).
def estimate_tokens(text: str) -> int:
    content = str(text or "")
    if not content:
        return 0
    cjk = sum(1 for ch in content if "\u4e00" <= ch <= "\u9fff")
    other = max(0, len(content) - cjk)
    # CJK denser; Latin-ish cheaper. Floor at 1 for non-empty.
    tokens = (cjk + 1) // 2 + (other + 3) // 4
    return max(1, tokens)


def estimate_messages_tokens(messages: Iterable[Mapping[str, Any]]) -> int:
    total = 0
    for item in messages:
        if not isinstance(item, Mapping):
            continue
        content = item.get("content")
        if content is None and isinstance(item.get("parts"), list):
            chunks: list[str] = []
            for part in item.get("parts") or []:
                if isinstance(part, Mapping):
                    chunks.append(str(part.get("text") or ""))
                else:
                    chunks.append(str(part or ""))
            content = "\n".join(chunks)
        total += estimate_tokens(str(content or ""))
    return total


@dataclass
class ContextBudgetReport:
    """Per-layer context budget for observability."""

    layers_chars: dict[str, int] = field(default_factory=dict)
    layers_tokens: dict[str, int] = field(default_factory=dict)
    total_chars: int = 0
    total_tokens: int = 0
    dialog_count: int = 0
    compact_triggered: bool = False
    notes: list[str] = field(default_factory=list)

    def set_layer(self, name: str, text: str) -> None:
        payload = str(text or "")
        chars = len(payload)
        tokens = estimate_tokens(payload) if payload.strip() else 0
        self.layers_chars[name] = chars
        self.layers_tokens[name] = tokens

    def finalize(self) -> "ContextBudgetReport":
        self.total_chars = sum(int(v) for v in self.layers_chars.values())
        self.total_tokens = sum(int(v) for v in self.layers_tokens.values())
        return self

    def as_dict(self) -> dict[str, Any]:
        return {
            "layers_chars": dict(self.layers_chars),
            "layers_tokens": dict(self.layers_tokens),
            "total_chars": int(self.total_chars),
            "total_tokens": int(self.total_tokens),
            "dialog_count": int(self.dialog_count),
            "compact_triggered": bool(self.compact_triggered),
            "notes": list(self.notes),
        }

    def log_line(self) -> str:
        parts = [
            f"{name}={self.layers_tokens.get(name, 0)}t/{self.layers_chars.get(name, 0)}c"
            for name in self.layers_chars
        ]
        return (
            f"total={self.total_tokens}t/{self.total_chars}c "
            f"dialog={self.dialog_count} compact={self.compact_triggered} "
            + " ".join(parts)
        )


def default_context_window_tokens() -> int:
    """
    Assumed model context window.

    Default 256k matches current long-context model deployments.
    Override with IKAROS_CONTEXT_WINDOW_TOKENS when the active model differs
    (e.g. 128000 for smaller windows).
    """
    return _env_int("IKAROS_CONTEXT_WINDOW_TOKENS", 256_000, minimum=8_000)


def default_compact_token_threshold() -> int:
    """
    Auto-compact when *dialog* estimated tokens exceed this.

    Do not compact early; wait until history approaches the window.
    Default = 75% of context window (~192k at 256k), leaving headroom for
    system prompt, tools, memory layers, and model output.
    """
    derived = max(8_000, int(default_context_window_tokens() * 0.75))
    return _env_int("IKAROS_COMPACT_TOKEN_THRESHOLD", derived, minimum=4_000)


def default_compact_message_threshold() -> int:
    # Secondary guard only (many tiny turns). Token threshold is primary.
    return _env_int("IKAROS_COMPACT_MESSAGE_THRESHOLD", 800, minimum=40)


def default_keep_recent_tokens() -> int:
    """
    After compact, keep this much recent dialog (~15% of window, ~38k at 256k)
    so multi-step tasks stay grounded without replaying the whole archive.
    """
    derived = max(4_000, int(default_context_window_tokens() * 0.15))
    return _env_int("IKAROS_COMPACT_KEEP_RECENT_TOKENS", derived, minimum=2_000)


def default_keep_recent_max_messages() -> int:
    return _env_int("IKAROS_COMPACT_KEEP_RECENT_MAX", 160, minimum=8)


def default_dialog_message_limit() -> int:
    return _env_int("IKAROS_CONTEXT_DIALOG_LIMIT", 400, minimum=16)


def default_assemble_recent_token_budget() -> int:
    """
    How much recent dialog to load when assembling a turn (pre- or post-compact).

    Default ~50% of window so long sessions stay usable without stuffing the
    entire history every turn once past compact.
    """
    derived = max(8_000, int(default_context_window_tokens() * 0.50))
    return _env_int("IKAROS_CONTEXT_RECENT_TOKEN_BUDGET", derived, minimum=4_000)


def select_recent_by_budget(
    rows: list[dict[str, Any]],
    *,
    token_budget: int,
    max_messages: int,
    min_messages: int = 2,
) -> list[dict[str, Any]]:
    """Keep the newest rows within token budget and message cap."""
    if not rows:
        return []
    safe_max = max(1, int(max_messages))
    safe_min = max(1, min(int(min_messages), safe_max, len(rows)))
    safe_budget = max(1, int(token_budget))

    selected: list[dict[str, Any]] = []
    used_tokens = 0
    for row in reversed(list(rows)):
        content = str(row.get("content") or "")
        cost = estimate_tokens(content)
        if selected and (
            used_tokens + cost > safe_budget or len(selected) >= safe_max
        ):
            break
        selected.append(row)
        used_tokens += cost
        if len(selected) >= safe_max:
            break

    if len(selected) < safe_min:
        selected = list(reversed(list(rows)[-safe_min:]))
    else:
        selected = list(reversed(selected))
    return selected


def join_budgeted_blocks(
    blocks: list[str],
    *,
    max_chars: int,
    priority_first: bool = True,
) -> str:
    """
    Join text blocks under a char budget.

    When priority_first is True, earlier blocks are protected and later blocks
    are trimmed (or dropped) first — used so durable long-term memory beats daily noise.
    """
    cleaned = [str(item or "").strip() for item in blocks if str(item or "").strip()]
    if not cleaned:
        return ""
    limit = max(0, int(max_chars))
    if limit <= 0:
        return ""

    if not priority_first:
        joined = "\n\n".join(cleaned)
        if len(joined) <= limit:
            return joined
        return joined[:limit].rstrip()

    kept: list[str] = []
    used = 0
    for index, block in enumerate(cleaned):
        separator = 2 if kept else 0  # "\n\n"
        remaining = limit - used - separator
        if remaining <= 0:
            break
        if len(block) <= remaining:
            kept.append(block)
            used += separator + len(block)
            continue
        # Prefer filling budget with a high-priority block rather than empty tail.
        if index == 0 or not kept:
            kept.append(block[:remaining].rstrip())
            used = limit
            break
        # Secondary blocks: take a head slice if there is meaningful room.
        if remaining >= 80:
            kept.append(block[:remaining].rstrip())
        break
    return "\n\n".join(item for item in kept if item).strip()
