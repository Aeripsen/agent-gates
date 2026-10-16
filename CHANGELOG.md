# Changelog

Dated entries, newest first, written from the commit history. Test counts are what
`python -m pytest projects/job-search/tests tools/engine/tests -q` printed at the time.

## 2026-10-16

- Added `tools/engine/injection_gate.py`: flags override phrasing, chat-template role tokens,
  invisible Unicode (tag characters decoded), markdown-image exfiltration links and send-to-an-
  address requests in tool output. 26 tests, including its documented misses pinned as passing.
- Added `examples/worked_examples.py`: one prompt-injection or tool-abuse scenario per gate,
  offline. 6 tests pin the outcomes the README quotes.
- Found while writing the grounding example: the support check reads the "2" in a model name
  like "2P" as a standalone number, so a quote that omits the model name drops a true claim. Pinned
  by a test, not fixed yet.
- README: a 3-minute section for reviewers, a Mermaid diagram, quickstart, limitations in one
  place. Added `CITATION.cff` and this file.
- Tests: 104 to 136.

## 2026-07-23

- README: CI status badge, and the test counts spelled out (63 for the two gates, 41 grounding,
  104 total).

## 2026-07-21

- Grounding gate gained a second postcondition: the quote must support the claim (numbers in the
  claim present in the quote, two shared content terms, word overlap over a threshold), not only
  appear in the source.
- Hand-labelled eval set for the claim/quote question, grown from 36 to 54 cases with negatives
  written to beat a word-overlap check. Precision at the default threshold reads 0.600 on the 54
  (0.889 on the first 36); the docs quote the harder number.
- Tests for the support check, including the gaps it still has.

## 2026-07-20

- Initial public extract: honesty gate, eligibility gate, intake-engine spine, free-model router.
- CI and grounding-gate tests.
