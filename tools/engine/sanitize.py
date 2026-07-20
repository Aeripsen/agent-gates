"""Sanitize layer: all external content is hostile until cleaned.

Strips the indirect-prompt-injection vectors (HTML comments, <script>/<style>, tags) before any
model sees the text. A structured API response (e.g. a JSON product feed) needs no sanitizing;
any HTML-based adapter (forums, listings, scraped pages) MUST pass its text through here first.
See tools/engine/README.md for the security model this belongs to.
"""
from __future__ import annotations

import re

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_SCRIPT_STYLE = re.compile(r"<(script|style)\b.*?</\1>", re.DOTALL | re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t\f\v]+")
_NL = re.compile(r"\n{3,}")


def strip_html(text: str, *, max_chars: int = 20000) -> str:
    """Remove comments, scripts, styles, and tags; collapse whitespace; truncate.

    Truncation caps obfuscation/buffer attacks. max_chars=0 disables the cap.
    """
    if not text:
        return ""
    text = _COMMENT.sub(" ", text)
    text = _SCRIPT_STYLE.sub(" ", text)
    text = _TAG.sub(" ", text)
    text = _WS.sub(" ", text)
    text = _NL.sub("\n\n", text).strip()
    if max_chars and len(text) > max_chars:
        text = text[:max_chars] + "\n...[truncated]"
    return text
