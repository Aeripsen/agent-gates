"""SQLite store for the intake engine: seen-set dedup + run counters.

Single-file DB at data/private/engine.db (gitignored, local only). This is what makes
"alert only on NEW matches" possible: a run diffs its findings against the seen-set and
only the unseen ones fire an alert. The meta table carries a consecutive-empty-run counter
for a fail-loud rule (e.g. 3 empty runs in a row -> "ingestion broken" alert).

This MVP keys on a stable identity string (URL, listing id, whatever is stable for your
source). A production version would add semantic/perceptual dedup on top; that is out of
scope here.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DB_PATH = REPO / "data" / "private" / "engine.db"


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.execute(
        "CREATE TABLE IF NOT EXISTS seen ("
        " key TEXT PRIMARY KEY, source TEXT, title TEXT, price TEXT,"
        " first_seen TEXT, last_seen TEXT)"
    )
    con.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
    return con


def is_first_run(con: sqlite3.Connection) -> bool:
    return con.execute("SELECT COUNT(*) FROM seen").fetchone()[0] == 0


def unseen(con: sqlite3.Connection, keys: list[str]) -> set[str]:
    known = {
        row[0]
        for row in con.execute(
            f"SELECT key FROM seen WHERE key IN ({','.join('?' * len(keys))})", keys
        )
    } if keys else set()
    return set(keys) - known


def record(con: sqlite3.Connection, items: list[tuple[str, str, str, str]]) -> None:
    """items = [(key, source, title, price)]. Upserts; bumps last_seen, keeps first_seen."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    con.executemany(
        "INSERT INTO seen (key, source, title, price, first_seen, last_seen)"
        " VALUES (?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(key) DO UPDATE SET source=excluded.source, title=excluded.title,"
        " price=excluded.price, last_seen=excluded.last_seen",
        [(k, s, t, p, now, now) for k, s, t, p in items],
    )
    con.commit()


def set_meta(con: sqlite3.Connection, k: str, v: str) -> None:
    con.execute(
        "INSERT INTO meta (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
        (k, v),
    )
    con.commit()


def get_meta(con: sqlite3.Connection, k: str) -> str | None:
    row = con.execute("SELECT v FROM meta WHERE k = ?", (k,)).fetchone()
    return row[0] if row else None


def bump_counter(con: sqlite3.Connection, name: str, *, reset: bool = False) -> int:
    """Increment (or reset to 0) a named counter; returns the new value."""
    value = 0 if reset else int(
        (con.execute("SELECT v FROM meta WHERE k = ?", (name,)).fetchone() or ["0"])[0]
    ) + 1
    con.execute(
        "INSERT INTO meta (k, v) VALUES (?, ?)"
        " ON CONFLICT(k) DO UPDATE SET v=excluded.v",
        (name, str(value)),
    )
    con.commit()
    return value
