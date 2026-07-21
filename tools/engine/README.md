# The intake engine: one spine, thin adapters

A small pattern for any "watch a source, tell me what changed" job (price/stock monitoring,
listing feeds, content radars): one shared pipeline shape, with a small adapter per source
instead of a separate scraper for each one.

## The shape (every job is these stages)

```
DISCOVER  -> FETCH      -> SANITIZE   -> EXTRACT+GROUND -> STORE   -> ALERT/BRIEF
(find URLs/  (pull raw     (strip the    (schema'd facts   (dedup,   (notify only
 sources)     content)      poison)        + substring       track     on what's
                                           proof)             seen)     new)
```

- **Discover** (`adapters/brave.py`) - turn one query into candidate URLs/domains. Dedup,
  strip tracking params.
- **Fetch** (e.g. `adapters/shopify.py`) - adapter's job. Prefer cheap structured endpoints
  (a JSON API) over parsing HTML; only fall back to HTML/JS-rendering when the source forces it.
- **Sanitize** (`sanitize.py`) - SECURITY, first-class. All external content is toxic until
  cleaned. Strip HTML comments, `<script>`, tags, before anything reaches a model. This is the
  layer that stops indirect prompt injection hidden in a scraped page from ever reaching the
  model doing extraction.
- **Extract + ground** (`ground.py`) - a model returns a strict schema (claim + **verbatim
  quote**). Two deterministic Python post-conditions: the quote must exist in the sanitized
  source text, and the claim's words must match the quote's. Fail either and the claim is
  rejected and can be re-tried. No fact survives without a found-in-source quote that is at
  least lexically about what the claim says.
- **Store** (`store.py`) - SQLite dedup by a stable key (URL, listing id), so a run only
  reports what is actually new, plus a counter for a fail-loud rule (N empty runs in a row means
  the ingestion path is broken, not that the world went quiet).
- **Alert** (`alert.py`) - a stateless notification call. The engine's terminal action is a
  notification or a written brief; nothing here auto-acts on the world (no auto-contact, no
  auto-purchase, no POST to the platform being watched).

## Why this design, not a per-source scraper

**The validation gate is what makes a free or weak model safe to use here.** A model extracting
facts from a scraped page cannot be trusted to type only what is true; it can be trusted to copy a
quote, and code can verify a copy. So instead of asking "is this LLM smart enough not to
hallucinate a price," the design makes hallucination structurally impossible for any fact that
must clear the gate: if the quote is not byte-for-byte (whitespace/case normalized) present in the
sanitized source, the claim is dropped, full stop. That is a $0-inference way to get a real
accuracy guarantee, not a probabilistic one.

Presence on its own has an obvious hole: copy a real sentence out of the page, attach it to any
claim you like, and the gate is satisfied. So the gate also compares the claim against its quote
lexically (`claim_supported`): every standalone number in the claim has to appear in the quote,
the two have to share at least two content terms, and their content-word overlap has to reach
`SUPPORT_THRESHOLD` scored against the shorter side. This is still $0 and still deterministic, but
it is word matching, not reading. On the 54 hand-labelled cases in `eval/relevance_cases.json`
(all with verbatim quotes, so presence alone keeps every one of them) it takes precision from
0.481 to 0.600 and costs 8 of 26 true claims. That number used to read 0.889 on the first
36 cases; the drop is not a regression in the code, it is 18 harder cases written specifically to
sit in the gate's blind spots (entity and unit swaps, dropped hedges, a number attached to the
wrong stat), and 10 of the 12 sneak-through negatives do sneak through. The full table, and the
per-case list of what it gets wrong, is in `eval/RESULTS.md`; regenerate with
`python tools/engine/eval/run_eval.py --write`.

What it does not catch is worth saying plainly: a real quote with an invented clause bolted on, a
negation flip, and anything that needs reasoning over the quote rather than word overlap. A
"grounded" claim is one whose evidence is real and on topic. It is not a true claim.

**Sanitize is not optional and comes before extraction, not after.** Treating fetched content as
hostile input is the same posture you'd take with any external, non-trusted text a model will
read: strip anything that could be interpreted as an instruction (HTML comments, script/style
blocks, hidden text) before the model ever sees it, so a page cannot inject "ignore previous
instructions" into your extraction pipeline.

## Security model (applies to every adapter you add)

1. Treat all scraped/listing/forum content as hostile (indirect prompt injection, hidden HTML
   comments, injection via images/EXIF). Sanitize BEFORE any model sees it.
2. Read-only by default. No auto-contact, no auto-pay, no POST to the platform being watched, no
   filesystem writes outside this engine's own data directory.
3. Two-model separation: a cheap/free model does extraction from sanitized text only; whatever
   consumes the engine's output (a human, or a more capable planning model) never ingests raw
   external bytes directly.
4. Schema-enforced output; anything off-schema is discarded and the item flagged anomalous
   rather than silently coerced into shape.
5. A human approval gate on anything irreversible. The engine's terminal action is a
   notification or a written brief; a person decides and acts.

## What is in this repo, and what is not

Included: `sanitize.py`, `ground.py`, `store.py`, `alert.py`, and two adapters
(`adapters/shopify.py` for structured-JSON catalogs, `adapters/brave.py` for web discovery) as
worked examples of the FETCH stage.

Not included: a `pipeline.py` orchestrator wiring all five stages end to end for a specific
domain, and the RANK stage (scoring/prioritizing extracted items), because both were tightly
coupled to a specific personal use case (what to buy, what to watch for) in the source project.
The pieces here are the reusable spine; wiring a full pipeline for your own source is the
remaining work, and is a reasonable-sized weekend project once you have discover/fetch/sanitize/
ground/store in hand.
