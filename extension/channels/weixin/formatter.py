from __future__ import annotations

import re


def markdown_to_weixin_text(text: str) -> str:
    """Normalize text for Weixin delivery while preserving Markdown syntax.

    Weixin chat bubbles can render Markdown, so this no longer strips emphasis,
    links, headings, or code fences. Only light whitespace normalization remains.
    """
    rendered = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not rendered:
        return ""

    rendered = re.sub(r"\n{3,}", "\n\n", rendered)
    return rendered.strip()
