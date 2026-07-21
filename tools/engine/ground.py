"""Grounding gate: no fact survives without a verbatim quote that also matches the claim.

Two deterministic post-conditions, both in Python, neither in the model's judgment:

1. PRESENCE (`quote_found`). The verbatim_quote must be a substring of the sanitized source text,
   whitespace-normalized and case-insensitive. A free/weak model cannot invent a price or spec out
   of nothing and have it survive.
2. SUPPORT (`claim_supported`). The claim's words must line up with the quote's words: every
   standalone number in the claim has to appear in the quote, the two have to share at least two
   content terms (or one shared number), and the content-word overlap has to reach
   SUPPORT_THRESHOLD, scored against the shorter side. A real quote bolted onto an unrelated claim
   fails this, so does a quote whose price or version number was edited in the claim.

On a miss the claim dies and the caller may re-ask with the rejection appended.

WHAT THIS GATE CANNOT CATCH. Read this before trusting a pass, same as honesty_gate.py.

The support check is lexical. It compares word sets; it does not read. Everything below still
walks through, and all of it is in the measured eval set at tools/engine/eval/:

- A QUOTE PLUS AN INVENTED RIDER. "Returns accepted within 30 days" quoted under the claim
  "Returns are accepted within 30 days and return shipping is refunded". The overlap is high
  because most of the claim really is in the quote; the added clause is free.
- A NEGATION OR TENSE FLIP. "Python 3.13 removed the deprecated imp module" quoted under "was
  deprecated but not removed" shares nearly every token with its quote.
- ANY REASONING OVER THE QUOTE. A range ("US sizes 7 through 13") does not support "size 11" here,
  because 11 is not in the quote. That is a false reject, not a catch, and it is the main cost of
  condition 1.
- A CLAIM WHOSE WORDS ALL COME FROM THE QUOTE BUT WHOSE MEANING DOES NOT. Swapping "domestic" for
  "international" while keeping the rest costs one term out of several.

Measured on the 36 hand-labelled cases in tools/engine/eval/relevance_cases.json, presence alone
kept every misattributed claim (precision 0.556); presence plus support keeps 2 of 16 of them
(precision 0.889) and drops 4 of 20 claims a human would have kept. Numbers and method are in
tools/engine/eval/RESULTS.md. That set is hand-written and small, so treat it as a regression
suite, not as a field accuracy estimate.

"Grounded" now means "the quote is really in the source and its words match the claim". It still
does not mean "true". Downstream consumers must read the (claim, quote) pair.

Claims are dicts with at least {"claim": str, "verbatim_quote": str}. Extra keys pass through.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo/tools on path

_WS = re.compile(r"\s+")
_TOKEN = re.compile(r"[a-z0-9]+(?:[-'.][a-z0-9]+)*")
_NUMBER = re.compile(r"(?<![a-z0-9])\d[\d,]*(?:\.\d+)?")

# Words that carry no evidence either way. Kept deliberately short: a long stoplist starts
# throwing away the words that make a claim specific.
_STOP = frozenset(
    """a an the is are was were be been being of in on at to for from with by and or but
    this that these those it its as all any some our we you they there here has have had
    will would can could may might do does did than then so if""".split()
)

SUPPORT_THRESHOLD = 0.7

_WORD_RE = re.compile(r"[a-z]")


def _norm(s: str) -> str:
    return _WS.sub(" ", s).strip().casefold()


def _stem(t: str) -> str:
    return t[:-1] if len(t) > 3 and t.endswith("s") and not t.endswith("ss") else t


def _terms(s: str) -> set[str]:
    return {_stem(t) for t in _TOKEN.findall(_norm(s)) if t not in _STOP and len(t) > 1}


def _numbers(s: str) -> set[str]:
    return {m.group(0).replace(",", "").rstrip(".") for m in _NUMBER.finditer(_norm(s))}


def quote_found(quote: str, source: str) -> bool:
    return bool(quote and quote.strip()) and _norm(quote) in _norm(source)


def support_score(claim: str, quote: str) -> float:
    """Overlap between the content words of a claim and of its quote, 0.0 to 1.0.

    Scored against whichever side is shorter, because a real quote is usually a fragment of a
    sentence and a real claim usually names a subject the fragment leaves implicit. Normalising
    by the claim alone would punish "The Norco Charger A2 is on sale for $899" quoting "on sale
    for $899"; normalising by the quote alone would punish a one-detail claim pulled out of a
    long quote.
    """
    ct, qt = _terms(claim), _terms(quote)
    if not ct or not qt:
        return 0.0
    shared = ct & qt
    return max(len(shared) / len(ct), len(shared) / len(qt))


def claim_supported(claim: str, quote: str, *, threshold: float = SUPPORT_THRESHOLD) -> bool:
    """Whether the quote's words back up the claim's words. Lexical only, see the module docstring.

    Three conditions, all required:
    1. every standalone number in the claim appears in the quote (a swapped price or version dies)
    2. at least two shared content terms, or one shared term that is a number (a single common
       word like "closure" or "Toronto" is not enough to tie a claim to a quote)
    3. support_score at or above `threshold`
    """
    cn = _numbers(claim)
    if cn - _numbers(quote):
        return False
    shared = _terms(claim) & _terms(quote)
    if len(shared) < 2 and not (len(shared) == 1 and not _WORD_RE.search(next(iter(shared)))):
        return False
    return support_score(claim, quote) >= threshold


def gate(
    claims: list[dict], source: str, *, threshold: float = SUPPORT_THRESHOLD
) -> tuple[list[dict], list[dict]]:
    """Split claims into (grounded, rejected): quote verbatim in source AND supporting the claim."""
    grounded, rejected = [], []
    for c in claims:
        if not isinstance(c, dict):
            rejected.append(c)
            continue
        quote = str(c.get("verbatim_quote", ""))
        if quote_found(quote, source) and claim_supported(
            str(c.get("claim", "")), quote, threshold=threshold
        ):
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
        bad_pairs = [
            {"claim": str(c.get("claim", ""))[:120], "quote": str(c.get("verbatim_quote", ""))[:120]}
            for c in bad[:5]
        ]
        prompt = user + (
            "\n\nThese claims were rejected: either the quote was not found verbatim in the "
            "source, or the quote did not match the claim (numbers in the claim must appear in "
            f"its quote): {json.dumps(bad_pairs, ensure_ascii=False)}. Re-extract ONLY those "
            "claims with EXACT character-for-character quotes copied from the source, each quote "
            "carrying the words and numbers its claim states, or omit them. Reply with ONLY the "
            "JSON array."
        )
    return grounded, rejected, used
