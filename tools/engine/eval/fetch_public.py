"""Fetch the public-benchmark injection cases used by gate_eval.py. Needs network; the eval does not.

This script is how tools/engine/eval/data/injection_public.json was made. It is never run by
gate_eval.py or by the tests: the committed JSON is the corpus, and this file records exactly
which rows of which dataset revision went into it, so the selection can be checked and repeated.

The selection rule for each source was fixed before any row was scored by the gate, and is a
plain index rule, not a choice of rows that look like attacks:

  deepset     deepset/prompt-injections, split test: the first 25 rows with label 1, in row order.
  gandalf     Lakera/gandalf_ignore_instructions, split test: rows 0 to 24.
  bipia       geodesic-research/bipia (a mirror of microsoft/BIPIA), split train: the 20 rows at
              offsets 0, 2062, 4124, ... (stride 2062). The case text is the `context` field,
              which is the benign email, table or code with the attack string inserted.
  nemotron    nvidia/Nemotron-RL-Agentic-Indirect-Prompt-Injection-v1, split train: the 20 rows
              at offsets 0, 63, 126, ... (stride 63). The case text is injection.injection_text,
              the string the benchmark hides inside a tool result.
  vitaminc    tals/vitaminc, split test: the 60 rows at offsets 0, 919, 1838, ... (stride 919),
              for the grounding gate. The evidence sentence is both the passage and the quote,
              the claim is the claim, SUPPORTS maps to supported and REFUTES / NOT ENOUGH INFO to
              unsupported. The error_type and hard fields are hand annotations added after the
              fetch (from reading the claim and evidence, before scoring); a re-fetch keeps them.

Each dataset's current commit sha is checked against the pinned one first. If a dataset has been
updated, the script stops instead of silently fetching different rows.

Run: python tools/engine/eval/fetch_public.py
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "data" / "injection_public.json"
OUT_GROUNDING = HERE / "data" / "grounding_vitaminc.json"

API = "https://datasets-server.huggingface.co/rows"
META = "https://huggingface.co/api/datasets/"

SOURCES = {
    "deepset": {
        "dataset": "deepset/prompt-injections",
        "sha": "4f61ecb038e9c3fb77e21034b22511b523772cdd",
        "licence": "Apache-2.0",
        "config": "default",
        "split": "test",
    },
    "gandalf": {
        "dataset": "Lakera/gandalf_ignore_instructions",
        "sha": "04737b65e90a6794ec227012e4a255a7def6344b",
        "licence": "MIT",
        "config": "default",
        "split": "test",
    },
    "bipia": {
        "dataset": "geodesic-research/bipia",
        "sha": "003f58372e1696726b7cddde274a74bee0b1938a",
        "licence": "CC-BY-SA-4.0 (mirror); upstream microsoft/BIPIA is MIT",
        "config": "bipia",
        "split": "train",
    },
    "vitaminc": {
        "dataset": "tals/vitaminc",
        "sha": "be6febb761b0b2807687e61e0b5282e459df2fa0",
        "licence": "CC-BY-SA-3.0",
        "config": "default",
        "split": "test",
    },
    "nemotron": {
        "dataset": "nvidia/Nemotron-RL-Agentic-Indirect-Prompt-Injection-v1",
        "sha": "d738d4f361cc38bb4d7a42b9066776dade5332f5",
        "licence": "CC-BY-4.0",
        "config": "default",
        "split": "train",
    },
}


def _get(url: str) -> dict:
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except OSError:
            if attempt == 3:
                raise
            time.sleep(2 ** (attempt + 1))
    raise RuntimeError("unreachable")


def _rows(src: dict, offset: int, length: int) -> list[dict]:
    q = urllib.parse.urlencode({
        "dataset": src["dataset"], "config": src["config"], "split": src["split"],
        "offset": offset, "length": length,
    })
    return _get(f"{API}?{q}")["rows"]


def _check_sha(name: str, src: dict) -> None:
    sha = _get(META + src["dataset"])["sha"]
    if sha != src["sha"]:
        raise SystemExit(f"{name}: dataset is at {sha}, pinned {src['sha']}; refusing to fetch")


def _case(name: str, src: dict, row_idx: int, text: str, family: str) -> dict:
    return {
        "id": f"{name}-{row_idx}",
        "label": "attack",
        "source": name,
        "dataset": src["dataset"],
        "revision": src["sha"],
        "split": src["split"],
        "row_idx": row_idx,
        "licence": src["licence"],
        "family": family,
        "format": "text",
        "text": text,
    }


def fetch() -> list[dict]:
    cases: list[dict] = []
    for name, src in SOURCES.items():
        _check_sha(name, src)

    src = SOURCES["deepset"]
    got = []
    for r in _rows(src, 0, 100) + _rows(src, 100, 100):
        if r["row"]["label"] == 1 and len(got) < 25:
            got.append(_case("deepset", src, r["row_idx"], r["row"]["text"], "direct_mixed"))
    cases += got

    src = SOURCES["gandalf"]
    for r in _rows(src, 0, 25):
        cases.append(_case("gandalf", src, r["row_idx"], r["row"]["text"], "direct_override"))

    src = SOURCES["bipia"]
    for i in range(20):
        r = _rows(src, i * 2062, 1)[0]
        fam = "indirect_" + r["row"]["attack_category"]
        c = _case("bipia", src, r["row_idx"], r["row"]["context"], fam)
        c["attack_name"] = r["row"]["attack_name"]
        cases.append(c)

    src = SOURCES["nemotron"]
    for i in range(20):
        r = _rows(src, i * 63, 1)[0]
        inj = r["row"]["injection"]
        c = _case("nemotron", src, r["row_idx"], inj["injection_text"],
                  "indirect_" + r["row"]["attack_category"])
        c["domain"] = r["row"]["domain"]
        cases.append(c)
    return cases


def fetch_vitaminc(previous: dict[str, dict]) -> list[dict]:
    src = SOURCES["vitaminc"]
    _check_sha("vitaminc", src)
    out = []
    for i in range(60):
        r = _rows(src, i * 919, 1)[0]
        row = r["row"]
        cid = f"vitaminc-{r['row_idx']}"
        old = previous.get(cid, {})
        out.append({
            "id": cid,
            "source": "vitaminc",
            "dataset": src["dataset"],
            "revision": src["sha"],
            "split": src["split"],
            "row_idx": r["row_idx"],
            "licence": src["licence"],
            "page": row["page"],
            "original_label": row["label"],
            "label": "supported" if row["label"] == "SUPPORTS" else "unsupported",
            "passage": row["evidence"],
            "quote": row["evidence"],
            "claim": row["claim"],
            "error_type": old.get("error_type", ""),
            "hard": old.get("hard", False),
            "canary": row["big_bench_canary"],
        })
    return out


def main() -> None:
    previous = {}
    if OUT_GROUNDING.exists():
        previous = {c["id"]: c for c in json.loads(OUT_GROUNDING.read_text(encoding="utf-8"))["cases"]}
    gcases = fetch_vitaminc(previous)
    OUT_GROUNDING.parent.mkdir(parents=True, exist_ok=True)
    gdoc = {
        "about": "Grounding cases copied verbatim from tals/vitaminc (CC-BY-SA-3.0, derived from "
                 "Wikipedia) by fetch_public.py, with hand-written error_type and hard fields. "
                 "Each row keeps the dataset's BIG-bench canary string so the data can be "
                 "filtered out of training sets. Not covered by this repo's MIT licence.",
        "cases": gcases,
    }
    OUT_GROUNDING.write_text(json.dumps(gdoc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(gcases)} cases to {OUT_GROUNDING}")
    cases = fetch()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "about": "Injection cases copied verbatim from public datasets by fetch_public.py. Each "
                 "case carries its dataset, revision, split, row index and licence. Licences "
                 "differ per source; see docs/EVAL.md. Not covered by this repo's MIT licence.",
        "cases": cases,
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(cases)} cases to {OUT}")


if __name__ == "__main__":
    main()
