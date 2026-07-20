"""Telegram alert sender: one stateless Bot API call, stdlib only (same shape as llm_router).

Two gotchas: group chat ids keep their leading '-', and the text must be URL-encoded. Reads
TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from the repo-root .env (gitignored). Failures are
printed and returned, never swallowed (fail loud, not silent).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


def _load_env() -> None:
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def _post(token: str, chat_id: str, text: str, who: str) -> bool:
    """Single stateless Bot API sendMessage call. Returns True on Telegram-confirmed delivery."""
    if not token or not chat_id:
        print(f"[alert] {who}: token/chat_id missing from .env; NOT sent")
        return False
    # ALERT_TAG (set only when running a second instance, e.g. a dev/staging deployment) marks
    # message origin, e.g. "[dev]", so two environments alerting at once are never confused.
    tag = os.environ.get("ALERT_TAG", "")
    if tag:
        text = f"{tag} {text}"
    # Telegram hard-caps messages at 4096 chars; truncate instead of erroring.
    if len(text) > 4000:
        text = text[:4000] + "\n...[truncated]"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage", data=data
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            ok = bool(json.load(resp).get("ok"))
    except (urllib.error.URLError, OSError, ValueError) as e:
        print(f"[alert] {who}: Telegram send FAILED: {e}")
        return False
    if not ok:
        print(f"[alert] {who}: Telegram responded ok=false; message not delivered")
    return ok


def send(text: str) -> bool:
    """Send one message to the main alert channel."""
    _load_env()
    return _post(os.environ.get("TELEGRAM_BOT_TOKEN", ""),
                 os.environ.get("TELEGRAM_CHAT_ID", ""), text, "main-bot")


def send_secondary(text: str) -> bool:
    """Send to an optional second bot/channel (TELEGRAM_GETUPDATES_*), useful for separating one
    alert type from another (e.g. errors vs. matches). Falls back to the main channel if the
    second bot is not configured, so a notification is never silently dropped.
    """
    _load_env()
    jt = os.environ.get("TELEGRAM_GETUPDATES_BOT_TOKEN", "")
    jc = os.environ.get("TELEGRAM_GETUPDATES_CHAT_ID", "")
    if jt and jc:
        return _post(jt, jc, text, "secondary-bot")
    print("[alert] secondary bot not configured; falling back to main channel")
    return send(text)
