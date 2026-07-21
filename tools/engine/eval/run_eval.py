"""Measure the grounding gate against the hand-labelled cases in relevance_cases.json.

Every case has a quote that is verbatim in its source, so the substring-only gate keeps all of
them; the question being measured is whether the gate can tell a quote that supports its claim
from a real quote stuck onto a claim it does not support.

Run: python tools/engine/eval/run_eval.py [--write]
--write regenerates RESULTS.md next to this file.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import ground  # noqa: E402

CASES = json.loads((HERE / "relevance_cases.json").read_text(encoding="utf-8"))["cases"]


def score(decide) -> dict:
    """decide(case) -> True to keep the claim. Positive class is a genuinely supported claim."""
    tp = fp = fn = tn = 0
    wrong = []
    for c in CASES:
        kept = decide(c)
        supported = c["label"] == "supported"
        if kept and supported:
            tp += 1
        elif kept:
            fp += 1
            wrong.append((c["id"], "kept a misattributed claim"))
        elif supported:
            fn += 1
            wrong.append((c["id"], "dropped a supported claim"))
        else:
            tn += 1
    kept_total = tp + fp
    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": tp / kept_total if kept_total else 0.0,
        "recall": tp / (tp + fn) if (tp + fn) else 0.0,
        "catch_rate": tn / (tn + fp) if (tn + fp) else 0.0,
        "accuracy": (tp + tn) / len(CASES),
        "wrong": wrong,
    }


def _row(name: str, r: dict) -> str:
    return (
        f"| {name} | {r['tp']} | {r['fp']} | {r['fn']} | {r['tn']} | "
        f"{r['precision']:.3f} | {r['recall']:.3f} | {r['catch_rate']:.3f} | {r['accuracy']:.3f} |"
    )


HEADER = (
    "| gate | kept+supported | kept+misattributed | dropped+supported | dropped+misattributed |"
    " precision | recall | misattribution catch | accuracy |\n"
    "|---|---|---|---|---|---|---|---|---|"
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    lines = [
        "# Grounding gate: claim/quote support evaluation",
        "",
        f"Run {date.today().isoformat()} by `python tools/engine/eval/run_eval.py --write` over the "
        f"{len(CASES)} hand-labelled cases in `relevance_cases.json` "
        f"({sum(c['label'] == 'supported' for c in CASES)} supported, "
        f"{sum(c['label'] == 'misattributed' for c in CASES)} misattributed).",
        "",
        "The cases were written by hand for this repo. They are a fixed regression set chosen to "
        "include the failure shapes that matter (swapped number, unrelated quote, quote plus an "
        "invented clause, negation flip), not a random sample of anything, so these numbers say "
        "what the gate does on these cases and nothing more.",
        "",
        HEADER,
    ]

    baseline = score(lambda c: ground.quote_found(c["quote"], c["source"]))
    lines.append(_row("substring only (old gate)", baseline))

    has_support = hasattr(ground, "claim_supported")
    if has_support:
        for t in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0):
            r = score(
                lambda c, t=t: ground.quote_found(c["quote"], c["source"])
                and ground.claim_supported(c["claim"], c["quote"], threshold=t)
            )
            mark = " (default)" if abs(t - ground.SUPPORT_THRESHOLD) < 1e-9 else ""
            lines.append(_row(f"substring + support, threshold {t:g}{mark}", r))

    lines.append("")

    if has_support:
        current = score(lambda c: bool(ground.gate([{"claim": c["claim"], "verbatim_quote": c["quote"]}], c["source"])[0]))
        lines += [
            f"At the shipped default (`SUPPORT_THRESHOLD = {ground.SUPPORT_THRESHOLD}`), "
            f"`ground.gate` keeps {current['tp'] + current['fp']} of {len(CASES)} claims: "
            f"{current['tp']} supported and {current['fp']} misattributed. It drops "
            f"{current['fn']} claims a human would have accepted.",
            "",
            "Cases the shipped gate gets wrong:",
            "",
        ]
        by_id = {c["id"]: c for c in CASES}
        for cid, why in current["wrong"]:
            note = by_id[cid].get("note", "")
            lines.append(f"- `{cid}` {why}" + (f" ({note})" if note else ""))
        lines.append("")

    out = "\n".join(lines) + "\n"
    print(out)
    if args.write:
        (HERE / "RESULTS.md").write_text(out, encoding="utf-8")


if __name__ == "__main__":
    main()
