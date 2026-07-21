# Grounding gate: claim/quote support evaluation

Run 2026-07-21 by `python tools/engine/eval/run_eval.py --write` over the 36 hand-labelled cases in `relevance_cases.json` (20 supported, 16 misattributed).

The cases were written by hand for this repo. They are a fixed regression set chosen to include the failure shapes that matter (swapped number, unrelated quote, quote plus an invented clause, negation flip), not a random sample of anything, so these numbers say what the gate does on these cases and nothing more.

| gate | kept+supported | kept+misattributed | dropped+supported | dropped+misattributed | precision | recall | misattribution catch | accuracy |
|---|---|---|---|---|---|---|---|---|
| substring only (old gate) | 20 | 16 | 0 | 0 | 0.556 | 1.000 | 0.000 | 0.556 |
| substring + support, threshold 0.3 | 17 | 4 | 3 | 12 | 0.810 | 0.850 | 0.750 | 0.806 |
| substring + support, threshold 0.4 | 17 | 4 | 3 | 12 | 0.810 | 0.850 | 0.750 | 0.806 |
| substring + support, threshold 0.5 | 17 | 4 | 3 | 12 | 0.810 | 0.850 | 0.750 | 0.806 |
| substring + support, threshold 0.6 | 17 | 4 | 3 | 12 | 0.810 | 0.850 | 0.750 | 0.806 |
| substring + support, threshold 0.7 (default) | 16 | 2 | 4 | 14 | 0.889 | 0.800 | 0.875 | 0.833 |
| substring + support, threshold 0.8 | 14 | 2 | 6 | 14 | 0.875 | 0.700 | 0.875 | 0.778 |
| substring + support, threshold 1 | 14 | 2 | 6 | 14 | 0.875 | 0.700 | 0.875 | 0.778 |

At the shipped default (`SUPPORT_THRESHOLD = 0.7`), `ground.gate` keeps 18 of 36 claims: 16 supported and 2 misattributed. It drops 4 claims a human would have accepted.

Cases the shipped gate gets wrong:

- `S4` dropped a supported claim (needs range reasoning: 11 is inside 7 through 13)
- `S6` dropped a supported claim
- `S7` dropped a supported claim (one shared content word, quote is a two-word fragment)
- `S16` dropped a supported claim (shipped / ships is the only tie between claim and quote after the place name)
- `M9` kept a misattributed claim (quote supports the first half, the refund clause is invented)
- `M16` kept a misattributed claim (negation flip, near-total token overlap with the quote)

