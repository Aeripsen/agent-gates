"""Measure the grounding gate and the injection gate on the labelled corpora in eval/data/.

Offline and deterministic: it reads only the committed JSON files, calls the gates as shipped,
and prints the same bytes on every run. No dates, no network, no randomness.

Convention, the same for both gates (note that RESULTS.md, from run_eval.py, uses the opposite):

  positive class   a bad item: an unsupported claim, or an injection attempt
  predicted bad    the gate rejects the claim, or flags the text
  false accept     a bad item the gate lets through        FAR = FN / bad items
  false reject     a good item the gate stops              FRR = FP / good items
  precision        TP / (TP + FP)    recall  TP / (TP + FN) = 1 - FAR

Every rate carries a 95% Wilson score interval. Per-stratum tables only print the rate that is
defined inside that stratum (FAR for a stratum of bad items, FRR for a stratum of good items).

Run:
  python tools/engine/eval/gate_eval.py            print the report
  python tools/engine/eval/gate_eval.py --write    regenerate GATE_RESULTS.md and gate_results.json
  python tools/engine/eval/gate_eval.py --check    exit 1 if the committed files are out of date
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
sys.path.insert(0, str(HERE.parent))

import ground  # noqa: E402
import injection_gate  # noqa: E402
from sanitize import strip_html  # noqa: E402

RESULTS_MD = HERE / "GATE_RESULTS.md"
RESULTS_JSON = HERE / "gate_results.json"

Z95 = 1.959963984540054


# ---- statistics --------------------------------------------------------------------------------


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float] | None:
    """95% Wilson score interval for k successes in n trials. None when n is 0."""
    if n == 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def rate(k: int, n: int) -> dict:
    ci = wilson(k, n)
    return {"k": k, "n": n, "value": (k / n) if n else None,
            "ci95": [ci[0], ci[1]] if ci else None}


def confusion(items: list[tuple[bool, bool]]) -> dict:
    """items: (is_bad, predicted_bad) pairs -> counts and the four rates."""
    tp = sum(1 for bad, pred in items if bad and pred)
    fn = sum(1 for bad, pred in items if bad and not pred)
    fp = sum(1 for bad, pred in items if not bad and pred)
    tn = sum(1 for bad, pred in items if not bad and not pred)
    return {
        "tp": tp, "fn": fn, "fp": fp, "tn": tn,
        "false_accept_rate": rate(fn, tp + fn),
        "false_reject_rate": rate(fp, fp + tn),
        "precision": rate(tp, tp + fp),
        "recall": rate(tp, tp + fn),
    }


# ---- loading -----------------------------------------------------------------------------------


def _load(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def grounding_cases() -> list[dict]:
    """Constructed and VitaminC cases in one shape: id, source, passage text, quote, claim, ..."""
    cons = _load("grounding_constructed.json")
    out = []
    for c in cons["cases"]:
        out.append({**c, "source": "constructed", "passage": cons["passages"][c["passage"]],
                    "passage_id": c["passage"]})
    for c in _load("grounding_vitaminc.json")["cases"]:
        out.append(dict(c))
    return out


def injection_cases() -> list[dict]:
    return _load("injection_public.json")["cases"] + _load("injection_constructed.json")["cases"]


# ---- deciding ----------------------------------------------------------------------------------


def grounding_decision(case: dict) -> str:
    """'accepted', or which check rejected it: 'presence' (quote not in passage) or 'support'."""
    if not ground.quote_found(case["quote"], case["passage"]):
        return "presence"
    kept, _ = ground.gate([{"claim": case["claim"], "verbatim_quote": case["quote"]}], case["passage"])
    return "accepted" if kept else "support"


def injection_flagged(case: dict, *, sanitize: bool) -> bool:
    """Gate alone: scan the raw text. With sanitize: HTML goes through strip_html first, and an
    attack whose recorded payload is gone after sanitizing counts as stopped (the model never
    reads it). JSON and plain text are never sanitized, as in the engine."""
    text = case["text"]
    if sanitize and case.get("format") == "html":
        text = strip_html(text)
        if case["label"] == "attack" and case.get("payload") and case["payload"] not in text:
            return True
    return bool(injection_gate.scan(text))


# ---- evaluating --------------------------------------------------------------------------------


def _strata(cases: list[dict], pairs: list[tuple[bool, bool]], key) -> dict:
    groups: dict[str, list[tuple[bool, bool]]] = defaultdict(list)
    for c, pr in zip(cases, pairs):
        groups[key(c)].append(pr)
    return {k: confusion(v) for k, v in sorted(groups.items())}


def evaluate_grounding() -> dict:
    cases = grounding_cases()
    decisions = [grounding_decision(c) for c in cases]
    pairs = [(c["label"] == "unsupported", d != "accepted") for c, d in zip(cases, decisions)]
    misses = [
        {"id": c["id"], "source": c["source"], "error_type": c["error_type"], "hard": c["hard"],
         "quote": c["quote"], "claim": c["claim"]}
        for c, d in zip(cases, decisions) if c["label"] == "unsupported" and d == "accepted"
    ]
    false_rejects = [
        {"id": c["id"], "source": c["source"], "error_type": c["error_type"], "rejected_by": d,
         "quote": c["quote"], "claim": c["claim"]}
        for c, d in zip(cases, decisions) if c["label"] == "supported" and d != "accepted"
    ]
    by_check: dict[str, int] = defaultdict(int)
    for c, d in zip(cases, decisions):
        if c["label"] == "unsupported" and d != "accepted":
            by_check[d] += 1
    return {
        "n": len(cases),
        "n_supported": sum(c["label"] == "supported" for c in cases),
        "n_unsupported": sum(c["label"] == "unsupported" for c in cases),
        "n_hard": sum(bool(c["hard"]) for c in cases),
        "overall": confusion(pairs),
        "by_source": _strata(cases, pairs, lambda c: c["source"]),
        "by_error_type": _strata(cases, pairs, lambda c: f"{c['label']}:{c['error_type']}"),
        "by_hard": _strata(
            [c for c in cases if c["label"] == "unsupported"],
            [pr for c, pr in zip(cases, pairs) if c["label"] == "unsupported"],
            lambda c: f"unsupported:{'hard' if c['hard'] else 'not_hard'}"),
        "unsupported_caught_by": dict(sorted(by_check.items())),
        "misses": misses,
        "false_rejects": false_rejects,
    }


def evaluate_injection() -> dict:
    cases = injection_cases()
    out = {
        "n": len(cases),
        "n_attack": sum(c["label"] == "attack" for c in cases),
        "n_benign": sum(c["label"] == "benign" for c in cases),
    }
    for mode, san in (("gate_only", False), ("sanitize_then_gate", True)):
        pairs = [(c["label"] == "attack", injection_flagged(c, sanitize=san)) for c in cases]
        out[mode] = {
            "overall": confusion(pairs),
            "by_source": _strata(cases, pairs, lambda c: f"{c['label']}:{c['source']}"),
            "by_origin": _strata(cases, pairs, lambda c: f"{c['label']}:"
                                 + ("constructed" if c["source"] == "constructed" else "public")),
            "by_family": _strata(cases, pairs, lambda c: f"{c['label']}:{c['family']}"),
            "misses": [
                {"id": c["id"], "source": c["source"], "family": c["family"], "text": c["text"]}
                for c, (bad, pred) in zip(cases, pairs) if bad and not pred
            ],
            "false_flags": [
                {"id": c["id"], "family": c["family"], "text": c["text"],
                 "markers": sorted({f.kind for f in injection_gate.scan(
                     strip_html(c["text"]) if san and c.get("format") == "html" else c["text"])})}
                for c, (bad, pred) in zip(cases, pairs) if not bad and pred
            ],
        }
    return out


def evaluate() -> dict:
    return {"grounding": evaluate_grounding(), "injection": evaluate_injection()}


# ---- rendering ---------------------------------------------------------------------------------


def _f(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.3f}"


def _r(r: dict) -> str:
    if r["n"] == 0:
        return "n/a (n=0)"
    lo, hi = r["ci95"]
    return f"{_f(r['value'])} [{_f(lo)}, {_f(hi)}] ({r['k']}/{r['n']})"


def _cell(s: str, limit: int = 110) -> str:
    """One table cell: invisible and control characters shown as escapes, pipes escaped."""
    out = []
    for ch in s:
        cat = unicodedata.category(ch)
        if ch in "\n\r\t":
            out.append(" ")
        elif cat in ("Cf", "Cc", "Co", "Cn") or 0xE0000 <= ord(ch) <= 0xE007F:
            out.append(f"\\u{ord(ch):04x}" if ord(ch) <= 0xFFFF else f"\\U{ord(ch):08x}")
        else:
            out.append(ch)
    text = " ".join("".join(out).split())
    if len(text) > limit:
        text = text[: limit - 3] + "..."
    return text.replace("|", "\\|")


def _overall_table(rows: list[tuple[str, dict]]) -> list[str]:
    lines = ["| setting | TP | FN | FP | TN | false-accept rate | false-reject rate | precision | recall |",
             "|---|---|---|---|---|---|---|---|---|"]
    for name, m in rows:
        lines.append(f"| {name} | {m['tp']} | {m['fn']} | {m['fp']} | {m['tn']} | "
                     f"{_r(m['false_accept_rate'])} | {_r(m['false_reject_rate'])} | "
                     f"{_r(m['precision'])} | {_r(m['recall'])} |")
    return lines


def _strata_table(strata: dict, bad_label: str, title: str) -> list[str]:
    lines = [f"| {title} | n | rate (95% Wilson) |", "|---|---|---|"]
    for key, m in strata.items():
        label, name = key.split(":", 1)
        if label == bad_label:
            lines.append(f"| {name} | {m['tp'] + m['fn']} | false accept {_r(m['false_accept_rate'])} |")
    for key, m in strata.items():
        label, name = key.split(":", 1)
        if label != bad_label:
            lines.append(f"| {name} ({label}) | {m['fp'] + m['tn']} | false reject {_r(m['false_reject_rate'])} |")
    return lines


def render_markdown(res: dict) -> str:
    g, inj = res["grounding"], res["injection"]
    L: list[str] = []
    L += [
        "# Gate evaluation: grounding gate and injection gate",
        "",
        "Generated by `python tools/engine/eval/gate_eval.py --write` from the JSON files in "
        "`tools/engine/eval/data/`. Offline and deterministic. Corpus sources, licences, "
        "construction and limits are in `docs/EVAL.md`; read that before quoting a number.",
        "",
        "Positive class is the bad item (unsupported claim, injection attempt). False-accept rate "
        "is the share of bad items the gate lets through; false-reject rate is the share of good "
        "items it stops. Brackets are 95% Wilson intervals, then (k/n).",
        "",
        "Precision depends on the ratio of bad to good items in the corpus, which was chosen "
        "by hand, so it is not a field estimate. The two rates are less sensitive to that mix.",
        "",
        "## Grounding gate (`ground.gate`)",
        "",
        f"{g['n']} cases: {g['n_supported']} supported, {g['n_unsupported']} unsupported, "
        f"{g['n_hard']} marked hard near-misses. Each case is (passage, verbatim quote, claim); "
        "the gate is called exactly as shipped, at `SUPPORT_THRESHOLD = "
        f"{ground.SUPPORT_THRESHOLD}`.",
        "",
    ]
    L += _overall_table([("all cases", g["overall"])]
                        + [(f"source: {k}", v) for k, v in g["by_source"].items()])
    L += ["", "By error type:", ""]
    L += _strata_table(g["by_error_type"], "unsupported", "error type")
    L += ["", "Unsupported claims, hard near-misses against the rest:", ""]
    L += _strata_table(g["by_hard"], "unsupported", "subset")
    caught = g["unsupported_caught_by"]
    L += ["", "Unsupported claims the gate rejected, by which check rejected them: "
          + ", ".join(f"{k} {v}" for k, v in caught.items()) + ".", ""]
    L += [f"### Unsupported claims the grounding gate accepts ({len(g['misses'])})", "",
          "| id | error type | hard | quote | claim |", "|---|---|---|---|---|"]
    for m in g["misses"]:
        L.append(f"| {m['id']} | {m['error_type']} | {'yes' if m['hard'] else 'no'} | "
                 f"{_cell(m['quote'], 80)} | {_cell(m['claim'], 90)} |")
    L += ["", f"### Supported claims the grounding gate rejects ({len(g['false_rejects'])})", "",
          "| id | type | rejected by | quote | claim |", "|---|---|---|---|---|"]
    for m in g["false_rejects"]:
        L.append(f"| {m['id']} | {m['error_type']} | {m['rejected_by']} | "
                 f"{_cell(m['quote'], 80)} | {_cell(m['claim'], 90)} |")

    L += [
        "",
        "## Injection gate (`injection_gate.scan`, with and without `sanitize.strip_html`)",
        "",
        f"{inj['n']} cases: {inj['n_attack']} attacks, {inj['n_benign']} benign. `gate only` scans "
        "the raw text. `sanitize then gate` first runs `strip_html` on the HTML cases, as the "
        "engine does, and counts an attack as stopped when its payload is gone after sanitizing.",
        "",
        "The constructed attack cases were written by someone who had read the gate's patterns, "
        "so recall on them is optimistic. The per-source rows keep them apart from the public "
        "benchmark rows.",
        "",
    ]
    L += _overall_table([("gate only, all cases", inj["gate_only"]["overall"]),
                         ("sanitize then gate, all cases", inj["sanitize_then_gate"]["overall"])])
    for mode, title in (("gate_only", "gate only"), ("sanitize_then_gate", "sanitize then gate")):
        L += ["", f"By source, {title}:", ""]
        L += _strata_table(inj[mode]["by_source"], "attack", "source")
        L += ["", f"Public benchmark rows pooled, against constructed rows, {title}:", ""]
        L += _strata_table(inj[mode]["by_origin"], "attack", "origin")
        L += ["", f"By attack family or benign category, {title}:", ""]
        L += _strata_table(inj[mode]["by_family"], "attack", "family")
    s = inj["sanitize_then_gate"]
    L += ["", f"### Attacks the injection gate misses, sanitize then gate ({len(s['misses'])})", "",
          "| id | source | family | text (first 110 characters, invisibles escaped) |",
          "|---|---|---|---|"]
    for m in s["misses"]:
        L.append(f"| {m['id']} | {m['source']} | {m['family']} | {_cell(m['text'])} |")
    L += ["", f"### Benign texts the injection gate flags, sanitize then gate ({len(s['false_flags'])})",
          "", "| id | category | markers | text |", "|---|---|---|---|"]
    for m in s["false_flags"]:
        L.append(f"| {m['id']} | {m['family']} | {', '.join(m['markers'])} | {_cell(m['text'])} |")
    return "\n".join(L) + "\n"


def render_json(res: dict) -> str:
    return json.dumps(res, ensure_ascii=True, indent=1, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Evaluate the grounding and injection gates.")
    ap.add_argument("--write", action="store_true", help="write GATE_RESULTS.md and gate_results.json")
    ap.add_argument("--check", action="store_true", help="fail if the committed results are stale")
    args = ap.parse_args(argv)
    res = evaluate()
    md, js = render_markdown(res), render_json(res)
    if args.check:
        stale = [p.name for p, body in ((RESULTS_MD, md), (RESULTS_JSON, js))
                 if not p.exists() or p.read_text(encoding="utf-8") != body]
        if stale:
            print("stale: " + ", ".join(stale) + "; run gate_eval.py --write")
            return 1
        print("committed results match a fresh run")
        return 0
    if args.write:
        RESULTS_MD.write_text(md, encoding="utf-8")
        RESULTS_JSON.write_text(js, encoding="utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
