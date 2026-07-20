"""Grounding gate: no fact survives without a verbatim, found-in-source quote.

The deterministic post-condition this engine is built around: a model must return, for every
claim, a verbatim_quote; Python asserts the quote is actually a substring of the sanitized
source text (whitespace-normalized, case-insensitive). On miss the claim dies, and the
caller may re-ask with the rejection appended. This is what makes free/weak models safe: even
a weak model cannot fabricate a price/spec/fact, because a quote not found in the page is
dropped by code, not by judgment.

Claims are dicts with at least {"claim": str, "verbatim_quote": str}. Extra keys pass through.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo/tools on path

_WS = re.compile(r"\s+")


def _norm(s: str) -> str:
    return _WS.sub(" ", s).strip().casefold()


def quote_found(quote: str, source: str) -> bool:
    return bool(quote and quote.strip()) and _norm(quote) in _norm(source)


def gate(claims: list[dict], source: str) -> tuple[list[dict], list[dict]]:
    """Split claims into (grounded, rejected) by the substring post-condition."""
    grounded, rejected = [], []
    for c in claims:
        if isinstance(c, dict) and quote_found(str(c.get("verbatim_quote", "")), source):
            grounded.append(c)
        else:
            rejected.append(c)
    return grounded, rejected


def _coerce_claims(obj):
    """Accept what free models actually return: a bare array of claims, a single claim object,
    or an object wrapping the list. {} / {"error": ...} -> no claims. Non-JSON-container -> None."""
    if isinstance(obj, list):
        return [c for c in obj if isinstance(c, dict)]
    if isinstance(obj, dict):
        for k in ("claims", "facts", "results", "items", "data"):
            if isinstance(obj.get(k), list):
                return [c for c in obj[k] if isinstance(c, dict)]
        if "claim" in obj or "verbatim_quote" in obj:  # single claim returned unwrapped
            return [obj]
        return []  # {} or {"error": "nothing relevant"} -> 0 claims, not a parse failure
    return None


def _parse_claims(raw: str) -> list[dict]:
    """Parse a model reply into claim dicts; tolerant of fences AND of object-shaped replies (free
    models constantly return a single object or {"claims": [...]} instead of a bare array)."""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
    try:
        out = _coerce_claims(json.loads(text))
        if out is not None:
            return out
    except json.JSONDecodeError:
        pass
    for opener, closer in (("[", "]"), ("{", "}")):
        start, end = text.find(opener), text.rfind(closer)
        if start != -1 and end > start:
            try:
                out = _coerce_claims(json.loads(text[start : end + 1]))
                if out is not None:
                    return out
            except json.JSONDecodeError:
                continue
    raise ValueError(f"no JSON array/object in reply: {text[:120]!r}")


def extract_grounded(
    system: str, user: str, source: str, *, retries: int = 2
) -> tuple[list[dict], list[dict], str]:
    """Ask the free router for claims about `source`, gate them, re-ask on rejects.

    Returns (grounded, rejected_after_final_try, backend_used). The system prompt should
    demand a JSON array of {"claim", "verbatim_quote", ...}; this function enforces it.
    """
    from llm_router import chat

    grounded: list[dict] = []
    rejected: list[dict] = []
    used = ""
    prompt = user
    for attempt in range(retries + 1):
        raw, used = chat(system, prompt, want_json=True)
        try:
            claims = _parse_claims(raw)
        except (ValueError, json.JSONDecodeError) as e:
            if attempt == retries:
                raise RuntimeError(f"unparseable extraction after {retries + 1} tries: {e}") from e
            prompt = user + f"\n\nYour previous reply was not a valid JSON array ({e}). Reply with ONLY the JSON array."
            continue
        ok, bad = gate(claims, source)
        grounded.extend(c for c in ok if c not in grounded)
        rejected = bad
        if not bad or attempt == retries:
            break
        bad_quotes = [str(c.get("verbatim_quote", ""))[:120] for c in bad[:5]]
        prompt = user + (
            "\n\nThese quotes were NOT found verbatim in the source and the claims were "
            f"rejected: {json.dumps(bad_quotes, ensure_ascii=False)}. Re-extract ONLY those "
            "claims with EXACT character-for-character quotes copied from the source, or omit "
            "them. Reply with ONLY the JSON array."
        )
    return grounded, rejected, used
