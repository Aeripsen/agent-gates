# Grounding gate: claim/quote support evaluation

Run 2026-07-21 by `python tools/engine/eval/run_eval.py --write` over the 54 hand-labelled cases in `relevance_cases.json` (26 supported, 28 misattributed).

The cases were written by hand for this repo. They are a fixed regression set chosen to include the failure shapes that matter (swapped number, unrelated quote, quote plus an invented clause, negation flip), not a random sample of anything, so these numbers say what the gate does on these cases and nothing more. The second batch (S21-S26, M17-M28) was written after the first results looked flattering: paraphrase positives with little word overlap, and negatives that keep every number and most words of the quote while changing what it says (entity, unit, hedge, quantifier, or which stat a number belongs to). A harder set is supposed to make the gate look worse; that is the information.

| gate | kept+supported | kept+misattributed | dropped+supported | dropped+misattributed | precision | recall | misattribution catch | accuracy |
|---|---|---|---|---|---|---|---|---|
| substring only (old gate) | 26 | 28 | 0 | 0 | 0.481 | 1.000 | 0.000 | 0.481 |
| substring + support, threshold 0.3 | 21 | 14 | 5 | 14 | 0.600 | 0.808 | 0.500 | 0.648 |
| substring + support, threshold 0.4 | 21 | 14 | 5 | 14 | 0.600 | 0.808 | 0.500 | 0.648 |
| substring + support, threshold 0.5 | 21 | 14 | 5 | 14 | 0.600 | 0.808 | 0.500 | 0.648 |
| substring + support, threshold 0.6 | 21 | 14 | 5 | 14 | 0.600 | 0.808 | 0.500 | 0.648 |
| substring + support, threshold 0.7 (default) | 18 | 12 | 8 | 16 | 0.600 | 0.692 | 0.571 | 0.630 |
| substring + support, threshold 0.8 | 16 | 6 | 10 | 22 | 0.727 | 0.615 | 0.786 | 0.704 |
| substring + support, threshold 1 | 16 | 5 | 10 | 23 | 0.762 | 0.615 | 0.821 | 0.722 |

At the shipped default (`SUPPORT_THRESHOLD = 0.7`), `ground.gate` keeps 30 of 54 claims: 18 supported and 12 misattributed. It drops 8 claims a human would have accepted.

Cases the shipped gate gets wrong:

- `S4` dropped a supported claim (needs range reasoning: 11 is inside 7 through 13)
- `S6` dropped a supported claim
- `S7` dropped a supported claim (one shared content word, quote is a two-word fragment)
- `S16` dropped a supported claim (shipped / ships is the only tie between claim and quote after the place name)
- `S21` dropped a supported claim (true paraphrase with zero shared content words except the subject)
- `S23` dropped a supported claim (entry / cost synonym, only the number and one word tie them)
- `S25` dropped a supported claim
- `S26` dropped a supported claim (allows / allowed do not stem to the same token)
- `M9` kept a misattributed claim (quote supports the first half, the refund clause is invented)
- `M16` kept a misattributed claim (negation flip, near-total token overlap with the quote)
- `M17` kept a misattributed claim (old price presented as the sale price; both numbers really are in the quote)
- `M18` kept a misattributed claim (precision and recall swapped; both numbers are in the quote)
- `M19` kept a misattributed claim (model number swapped, A3 for A2; not a standalone number so the number check never sees it)
- `M20` kept a misattributed claim (drops the up-to hedge; every claim word is in the quote)
- `M21` kept a misattributed claim (drops the modal; may-be-eligible becomes are-eligible and both modal words are stopwords)
- `M22` kept a misattributed claim (waitlist swapped for registration, everything else identical)
- `M23` kept a misattributed claim (some flipped to all; both quantifiers are stopwords so the swap is invisible to the gate)
- `M24` kept a misattributed claim (direction flipped, increased to decreased, one antonym in an otherwise identical sentence)
- `M25` kept a misattributed claim (unit swapped, kg to lb; the number check only looks at digits)
- `M26` kept a misattributed claim (paraphrase that shifts the subject: instructor tenure is not course availability)

