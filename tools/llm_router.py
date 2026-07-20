#!/usr/bin/env python3
"""Free-model offload router.

One entry point, OpenRouter-first, then Groq, then Gemini x2. Tries each backend in
order until one returns; raises only if all fail. Use this for bulk/cheap work
(summarization, extraction, ranking) so you do not burn a paid API budget on tasks
that a free-tier model handles fine.

Stdlib only (urllib). Keys come from a repo-root .env (gitignored), never hardcoded.

Usage:
    from llm_router import chat
    text, used = chat("system instruction", "user prompt", want_json=True)

CLI:
    python tools/llm_router.py            # ping every backend, report which keys work
"""
from __future__ import annotations
import json, os, urllib.request, urllib.error
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
# Some providers (Groq) sit behind Cloudflare and 403 urllib's default user-agent.
UA = "Mozilla/5.0 (llm_router; https://github.com/Aeripsen/agent-gates)"


def _load_env() -> None:
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


_load_env()

# Ordered backends. Free-first; resilient to one model id going stale (falls through).
# type: "openai" = OpenAI-compatible /chat/completions; "gemini" = generativelanguage REST.
# NOTE: OpenRouter's ":free" pool ROTATES. Model ids fall off the free tier without notice;
# re-check the live free list periodically: GET https://openrouter.ai/api/v1/models,
# filter pricing==0, and update the model ids below.
BACKENDS = [
    {"name": "openrouter:model-a", "type": "openai",
     "base": "https://openrouter.ai/api/v1", "key_env": "OPENROUTER_API_KEY",
     "model": "qwen/qwen3-coder:free"},
    {"name": "openrouter:model-b", "type": "openai",
     "base": "https://openrouter.ai/api/v1", "key_env": "OPENROUTER_API_KEY",
     "model": "qwen/qwen3-next-80b-a3b-instruct:free"},
    {"name": "openrouter:model-c", "type": "openai",
     "base": "https://openrouter.ai/api/v1", "key_env": "OPENROUTER_API_KEY",
     "model": "openai/gpt-oss-120b:free"},
    {"name": "groq:llama-3.3-70b", "type": "openai",
     "base": "https://api.groq.com/openai/v1", "key_env": "GROQ_API_KEY",
     "model": "llama-3.3-70b-versatile"},
    # Separate Groq model = separate per-model daily token quota, so this is a genuine extra
    # fallback (not a duplicate) when the 70b model hits its own TPD cap. Weaker model, used
    # only as a last-resort free tier before Gemini/paid.
    {"name": "groq:llama-3.1-8b-instant", "type": "openai",
     "base": "https://api.groq.com/openai/v1", "key_env": "GROQ_API_KEY",
     "model": "llama-3.1-8b-instant"},
    {"name": "gemini:flash(key1)", "type": "gemini",
     "base": "https://generativelanguage.googleapis.com/v1beta", "key_env": "GEMINI_API_KEY",
     "model": "gemini-flash-latest"},
    {"name": "gemini:flash(key2)", "type": "gemini",
     "base": "https://generativelanguage.googleapis.com/v1beta", "key_env": "GEMINI_API_KEY_2",
     "model": "gemini-flash-latest"},
]


def _post(url: str, headers: dict, payload: dict, timeout: int) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _call_openai(b, system, user, want_json, temperature, max_tokens, timeout):
    key = os.environ.get(b["key_env"], "")
    if not key:
        raise RuntimeError(f"no key in {b['key_env']}")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json",
               "User-Agent": UA}
    if "openrouter" in b["name"]:
        headers["HTTP-Referer"] = os.environ.get(
            "OPENROUTER_REFERRER", "https://github.com/Aeripsen/agent-gates")
        headers["X-Title"] = "llm-router"
    payload = {
        "model": b["model"],
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if want_json:
        payload["response_format"] = {"type": "json_object"}
    data = _post(f"{b['base']}/chat/completions", headers, payload, timeout)
    return data["choices"][0]["message"].get("content") or ""


def _call_gemini(b, system, user, want_json, temperature, max_tokens, timeout):
    key = os.environ.get(b["key_env"], "")
    if not key:
        raise RuntimeError(f"no key in {b['key_env']}")
    headers = {"Content-Type": "application/json", "X-goog-api-key": key, "User-Agent": UA}
    # gemini-flash is a thinking model; give headroom so reasoning tokens don't starve output.
    gen = {"temperature": temperature, "maxOutputTokens": max(max_tokens, 2048)}
    if want_json:
        gen["responseMimeType"] = "application/json"
    payload = {
        "contents": [{"parts": [{"text": user}]}],
        "systemInstruction": {"parts": [{"text": system}]},
        "generationConfig": gen,
    }
    url = f"{b['base']}/models/{b['model']}:generateContent"
    data = _post(url, headers, payload, timeout)
    cand = (data.get("candidates") or [{}])[0]
    parts = cand.get("content", {}).get("parts")
    if not parts:
        raise RuntimeError(f"gemini returned no parts (finishReason={cand.get('finishReason')})")
    return parts[0]["text"]


def chat(system: str, user: str, *, want_json: bool = False, temperature: float = 0.2,
         max_tokens: int = 4096, timeout: int = 180, verbose: bool = False,
         exclude: list[str] | None = None):
    """Return (text, backend_name). Tries each backend until one succeeds.

    exclude: backend names to skip (see BACKENDS[*]["name"]). Use this to keep weak small
    models out of rotation for tasks where a wrong answer is worse than no answer (fabrication
    is more likely from small free models when asked to write claims about a specific person or
    fact set). Fine for non-critical bulk work (summarization, ranking).
    """
    errors = []
    excl = set(exclude or [])
    for b in BACKENDS:
        if b["name"] in excl:
            continue
        try:
            fn = _call_openai if b["type"] == "openai" else _call_gemini
            text = fn(b, system, user, want_json, temperature, max_tokens, timeout)
            if text and text.strip():
                if verbose:
                    print(f"[llm_router] used {b['name']}")
                return text, b["name"]
            errors.append(f"{b['name']}: empty response")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore")[:200]
            errors.append(f"{b['name']}: HTTP {e.code} {body}")
        except Exception as e:  # noqa: BLE001 - failures must be visible, try next backend
            errors.append(f"{b['name']}: {type(e).__name__} {e}")
    raise RuntimeError("all backends failed:\n  " + "\n  ".join(errors))


if __name__ == "__main__":
    # Ping each backend independently so we can see exactly which keys work.
    print(f".env: {ENV_PATH} (exists={ENV_PATH.exists()})")
    for b in BACKENDS:
        try:
            fn = _call_openai if b["type"] == "openai" else _call_gemini
            out = fn(b, "You are a terse assistant.", "Reply with the single word: pong",
                     False, 0.0, 16, 60)
            print(f"OK   {b['name']:28s} -> {out.strip()[:40]!r}")
        except urllib.error.HTTPError as e:
            print(f"FAIL {b['name']:28s} -> HTTP {e.code} {e.read().decode('utf-8','ignore')[:120]}")
        except Exception as e:  # noqa: BLE001
            print(f"FAIL {b['name']:28s} -> {type(e).__name__}: {str(e)[:120]}")
