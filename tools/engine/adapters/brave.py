"""Brave Search adapter: the DISCOVER stage.

Turns a query into a list of candidate URLs/domains so the engine stops relying on a
hand-maintained domain list. Free tier available. Key in .env as BRAVE_API_KEY.
Docs: https://api.search.brave.com/app/documentation/web-search
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
UA = "Mozilla/5.0 (agent-gates intake-engine; research use)"
_ENV = Path(__file__).resolve().parents[3] / ".env"  # adapters -> engine -> tools -> repo root

# Brave rejects an over-long q with HTTP 422 ("too_long"). Documented limit: "Maximum of 400
# characters and 50 words in the query." Clamp to both, with a little margin.
MAX_Q_CHARS = 390
MAX_Q_WORDS = 50


def clamp_query(query: str) -> str:
    """Collapse whitespace/newlines and trim to Brave's 400-char / 50-word ceiling. A hard safety
    net so no caller can ever send a too-long q (a 422 that would otherwise silently zero out a
    research run)."""
    q = " ".join(str(query).split())  # strip newlines + collapse runs of whitespace
    words = q.split(" ")
    if len(words) > MAX_Q_WORDS:
        q = " ".join(words[:MAX_Q_WORDS])
    if len(q) > MAX_Q_CHARS:
        q = q[:MAX_Q_CHARS].rsplit(" ", 1)[0]  # don't cut mid-word
    return q


def _load_key() -> str:
    key = os.environ.get("BRAVE_API_KEY", "")
    if not key and _ENV.exists():
        for line in _ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("BRAVE_API_KEY=") and "=" in line:
                key = line.split("=", 1)[1].strip()
                break
    if not key:
        raise RuntimeError("BRAVE_API_KEY not set (env or .env)")
    return key


@dataclass
class Hit:
    title: str
    url: str
    description: str

    @property
    def domain(self) -> str:
        return urlsplit(self.url).netloc.lower()

    @property
    def origin(self) -> str:
        p = urlsplit(self.url)
        return f"{p.scheme}://{p.netloc}"


def search(query: str, *, count: int = 10, country: str = "US", timeout: int = 25,
           offset: int = 0, freshness: str | None = None) -> list[Hit]:
    """Run one Brave web search. count<=20 per request. `offset` (0-9) pages through results so a
    caller can pull beyond the first page (breadth). `freshness` (pd/pw/pm/py or a
    YYYY-MM-DDtoYYYY-MM-DD range) biases toward recent pages. Returns [] (with a one-line warning)
    on a non-200 instead of aborting the caller, so one bad query never zeros out a whole run."""
    q = clamp_query(query)
    p = {"q": q, "count": min(count, 20), "country": country, "offset": max(0, min(offset, 9))}
    if freshness:
        p["freshness"] = freshness
    params = urllib.parse.urlencode(p)
    req = urllib.request.Request(
        f"{ENDPOINT}?{params}",
        headers={
            "User-Agent": UA,
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": _load_key(),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                import gzip
                raw = gzip.decompress(raw)
    except urllib.error.HTTPError as e:
        print(f"  [brave] HTTP {e.code} for {q[:80]!r}: {e.read()[:160]!r}")
        return []
    data = json.loads(raw)
    results = (data.get("web", {}) or {}).get("results", []) or []
    return [
        Hit(
            title=(r.get("title", "") or "").strip(),
            url=(r.get("url", "") or "").strip(),
            description=(r.get("description", "") or "").strip(),
        )
        for r in results
        if r.get("url")
    ]


def discover_origins(queries: list[str], *, per_query: int = 10) -> list[str]:
    """Run several queries and return a deduped list of site origins (scheme://host) to probe."""
    seen: dict[str, None] = {}
    for q in queries:
        try:
            for hit in search(q, count=per_query):
                seen.setdefault(hit.origin, None)
        except Exception as e:  # noqa: BLE001 - surface but keep going
            print(f"  [brave] query failed: {q!r}: {e}")
    return list(seen)


if __name__ == "__main__":
    hits = search("site:example.com product catalog", count=8)
    for h in hits:
        print(f"{h.domain:35s} {h.url}")
