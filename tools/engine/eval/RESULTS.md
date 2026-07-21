# Grounding gate: claim/quote support evaluation

Run 2026-07-21 by `python tools/engine/eval/run_eval.py --write` over the 36 hand-labelled cases in `relevance_cases.json` (20 supported, 16 misattributed).

The cases were written by hand for this repo. They are a fixed regression set chosen to include the failure shapes that matter (swapped number, unrelated quote, quote plus an invented clause, negation flip), not a random sample of anything, so these numbers say what the gate does on these cases and nothing more.

| gate | kept+supported | kept+misattributed | dropped+supported | dropped+misattributed | precision | recall | misattribution catch | accuracy |
|---|---|---|---|---|---|---|---|---|
| substring only (old gate) | 20 | 16 | 0 | 0 | 0.556 | 1.000 | 0.000 | 0.556 |

