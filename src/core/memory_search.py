from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)
_STOPWORDS = {
    "的",
    "了",
    "吗",
    "呢",
    "啊",
    "吧",
    "是",
    "在",
    "和",
    "与",
    "或",
    "及",
    "就",
    "都",
    "也",
    "很",
    "还",
    "把",
    "被",
    "让",
    "给",
    "对",
    "从",
    "到",
    "我",
    "你",
    "他",
    "她",
    "它",
    "我们",
    "你们",
    "他们",
    "这",
    "那",
    "一个",
    "一下",
    "什么",
    "怎么",
    "如何",
    "为什么",
    "可以",
    "需要",
    "帮我",
    "请",
    "记住",
    "忘记",
    "查看",
    "记忆",
    "the",
    "a",
    "an",
    "is",
    "are",
    "to",
    "of",
    "and",
    "or",
    "for",
    "in",
    "on",
    "my",
    "me",
    "you",
    "please",
    "remember",
    "forget",
    "memory",
}


@dataclass(frozen=True)
class MemoryHit:
    text: str
    source: str
    score: float
    tier: str = ""


def tokenize_query(text: str) -> list[str]:
    raw = str(text or "").strip().lower()
    if not raw:
        return []
    tokens: list[str] = []
    seen: set[str] = set()

    def _add(token: str) -> None:
        item = str(token or "").strip().lower()
        if not item or item in _STOPWORDS:
            return
        if len(item) == 1 and not ("\u4e00" <= item <= "\u9fff"):
            return
        if item in seen:
            return
        seen.add(item)
        tokens.append(item)

    for match in _TOKEN_RE.findall(raw):
        _add(match)
        # CJK bigrams help short Chinese queries match longer facts.
        if len(match) >= 2 and all("\u4e00" <= ch <= "\u9fff" for ch in match):
            for index in range(len(match) - 1):
                _add(match[index : index + 2])
    return tokens


def score_text(text: str, query_tokens: Iterable[str]) -> float:
    payload = str(text or "").strip().lower()
    if not payload:
        return 0.0
    tokens = [str(item or "").strip().lower() for item in query_tokens if str(item or "").strip()]
    if not tokens:
        return 0.0
    score = 0.0
    for token in tokens:
        if token not in payload:
            continue
        # Longer tokens are more informative.
        score += min(4.0, 1.0 + (len(token) / 4.0))
        if payload.startswith(token) or f"：{token}" in payload or f":{token}" in payload:
            score += 0.5
    return score


def rank_memory_candidates(
    candidates: list[dict[str, str]],
    *,
    query: str,
    limit: int = 5,
    min_score: float = 1.0,
) -> list[MemoryHit]:
    tokens = tokenize_query(query)
    if not tokens:
        return []
    scored: list[MemoryHit] = []
    for item in candidates:
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        points = score_text(text, tokens)
        if points < float(min_score):
            continue
        scored.append(
            MemoryHit(
                text=text,
                source=str(item.get("source") or "").strip() or "memory",
                score=float(points),
                tier=str(item.get("tier") or "").strip(),
            )
        )
    scored.sort(key=lambda hit: (-hit.score, hit.text))
    # Dedupe by normalized text.
    output: list[MemoryHit] = []
    seen: set[str] = set()
    for hit in scored:
        key = re.sub(r"\s+", "", hit.text.lower())[:240]
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(hit)
        if len(output) >= max(1, int(limit)):
            break
    return output
