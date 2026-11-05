# Evaluating the grounding gate and the injection gate

This page describes the labelled corpora in `tools/engine/eval/data/`, how they were built, where
each case comes from and under which licence, how the numbers in
`tools/engine/eval/GATE_RESULTS.md` are computed, and what they do not tell you.

Reproduce every number offline, with no keys and no network:

```
python tools/engine/eval/gate_eval.py --write   # regenerates GATE_RESULTS.md and gate_results.json
python tools/engine/eval/gate_eval.py --check   # exit 1 if the committed files are out of date
```

`tools/engine/tests/test_gate_eval.py` runs the `--check` comparison in CI, so a change to a gate
or to the corpus that moves a number fails the build until the results are regenerated.

## What the gates are

Both gates are rules written in Python. Neither one calls a model or reads meaning.

- `ground.gate` takes a claim, a quote and the source text. It keeps the claim only if the quote
  is a case- and whitespace-insensitive substring of the source (presence), and the claim's words
  line up with the quote's words (support): every standalone number in the claim is in the quote,
  at least two content words are shared, and word overlap reaches `SUPPORT_THRESHOLD` (0.7).
- `injection_gate.scan` looks for five kinds of marker in a string: override phrases, chat
  template role tokens, invisible Unicode, markdown images whose URL has a query string, and
  send-to-an-address or raw tool-call keys. `sanitize.strip_html` runs before it on HTML and
  removes comments, scripts, styles and tags.

What follows from that, before any number:

- The grounding gate can catch a changed digit, an unrelated quote, and a quote that is not in the
  source. It cannot catch anything that keeps the quote's words and changes the meaning: a
  swapped entity or unit, a dropped hedge, a negation, an added clause. It also cannot follow a
  paraphrase or do arithmetic, so it rejects true claims written in other words.
- The injection gate can catch the exact phrasings and characters on its lists. It cannot catch
  paraphrase, other languages, encodings, or an instruction that reads like ordinary data, which
  is most of what the public benchmarks contain. It also flags ordinary text that uses its words
  for other reasons (security writing, hiring emails, prompt format docs, image CDN URLs).

## Metric definitions

The positive class is the bad item: an unsupported claim, or an injection attempt. A gate
"predicts bad" when it rejects the claim or flags the text.

| name | formula | meaning |
|---|---|---|
| false-accept rate (FAR) | FN / (TP + FN) | share of bad items the gate lets through |
| false-reject rate (FRR) | FP / (FP + TN) | share of good items the gate stops |
| precision | TP / (TP + FP) | share of the gate's rejections that were right |
| recall | TP / (TP + FN) | 1 minus FAR |

Every rate has a 95% Wilson score interval (z = 1.959964). A stratum with no items prints
`n/a`. Inside a stratum that holds only bad items (one error type) only FAR is defined, and inside
a stratum of good items only FRR, so the per-type tables print one rate each.

The older `tools/engine/eval/RESULTS.md` (from `run_eval.py`, 54 cases) uses the opposite
convention, with the supported claim as the positive class. It is left unchanged.

Precision depends on the share of bad items in the corpus, and that share was set by hand
(about 56% unsupported for grounding, 60% attacks for injection). Do not read precision as the
precision you would see on real traffic. FAR and FRR are per class and do not depend on the mix,
but they do depend on which kinds of case were written, which is the next section.

## Grounding corpus: 320 cases

Each case is (passage, verbatim quote, claim, label, error type, hard). The gate is called with
the passage as the source and the quote as `verbatim_quote`, exactly as `ground.gate` is called in
the engine.

### `grounding_constructed.json`: 260 cases, written for this repo

52 invented passages (product listings, policies, notices, release notes, study summaries), 5
claims each: 2 supported, 3 unsupported. Written by the author of this evaluation, who had read
`ground.py` before writing them. The passages are not copied from anywhere; the facts about real
software (Python 3.12 removing distutils, Rust 1.85) are paraphrased from public release notes.

`hard` marks a near-miss: an unsupported claim that keeps most of its quote's words and changes
one thing. It was set when each case was written, before the gate was run on it. 90 of the 156
unsupported constructed cases are hard.

### `grounding_vitaminc.json`: 60 cases from a public dataset

| field | value |
|---|---|
| dataset | `tals/vitaminc` on Hugging Face, revision `be6febb761b0b2807687e61e0b5282e459df2fa0` |
| paper | Schuster, Fisch, Barzilay. Get Your Vitamin C! Robust Fact Verification with Contrastive Evidence. NAACL 2021. |
| licence | CC BY-SA 3.0 (derived from Wikipedia revisions) |
| selection | split `test`, rows at offsets 0, 919, 1838, ... (stride 919), 60 rows, fixed before scoring |
| mapping | evidence sentence is both passage and quote; SUPPORTS is supported, REFUTES and NOT ENOUGH INFO are unsupported |

The `error_type` and `hard` fields were added by hand from reading each claim against its
evidence, before the gate was run. The dataset labels were kept as published, including a few
that look wrong to this reader (row 54221 is labelled SUPPORTS, but its evidence is about local
governance and the claim is about global governance), and rows whose evidence contradicts the
real world (rows 38598 and 51464 read like VitaminC's synthetic revisions); the label is about
the evidence as given, so those stay. Each row
keeps VitaminC's BIG-bench canary string. This file is under CC BY-SA 3.0, not the repo's MIT
licence.

### Error types

| type | label | what changed between quote and claim |
|---|---|---|
| exact | supported | nothing, or only the subject the quote left implicit |
| paraphrase | supported | same meaning, different words |
| fragment | supported | a very short quote; the claim names the subject |
| reasoning | supported | needs arithmetic, a range or a comparison ("size 10" from "sizes 7 through 13") |
| number_changed | unsupported | a number, date or ordering of numbers differs |
| unit_changed | unsupported | same number, different unit (kg to lb, km to miles) |
| entity_swapped | unsupported | a name, place, product, role or which-is-which differs |
| overclaim | unsupported | a hedge or limit is dropped ("up to", "may", "some", "under 18") |
| unsupported_inference | unsupported | the claim draws a conclusion the passage does not state |
| fabricated_detail | unsupported | the quote is supported, the claim adds an invented clause |
| negation_flip | unsupported | the claim says the opposite |
| unrelated_quote | unsupported | the quote is real but about something else |
| quote_not_in_source | unsupported | the quote itself is not in the passage |

## Injection corpus: 123 attacks, 81 benign

### Public benchmark rows: `injection_public.json`, 90 attacks

Copied verbatim by `tools/engine/eval/fetch_public.py`, which pins each dataset revision and
refuses to run if the dataset has changed. The eval and the tests never run the fetch script. The
selection rule for each source is an index rule, fixed before any row was scored, so it does not
pick rows that happen to match the gate.

| source key | dataset and revision | licence | selection | rows |
|---|---|---|---|---|
| `deepset` | `deepset/prompt-injections` @ `4f61ecb038e9c3fb77e21034b22511b523772cdd` | Apache-2.0 | split test, first 25 rows with label 1 | 25 |
| `gandalf` | `Lakera/gandalf_ignore_instructions` @ `04737b65e90a6794ec227012e4a255a7def6344b` | MIT | split test, rows 0 to 24 | 25 |
| `bipia` | `geodesic-research/bipia` @ `003f58372e1696726b7cddde274a74bee0b1938a`, a mirror of `microsoft/BIPIA` | mirror: CC BY-SA 4.0; upstream code: MIT | split train, offsets 0, 2062, ... (stride 2062), `context` field | 20 |
| `nemotron` | `nvidia/Nemotron-RL-Agentic-Indirect-Prompt-Injection-v1` @ `d738d4f361cc38bb4d7a42b9066776dade5332f5` | CC BY 4.0 | split train, offsets 0, 63, ... (stride 63), `injection.injection_text` | 20 |

Papers: BIPIA is Yi et al., Benchmarking and Defending Against Indirect Prompt Injection Attacks
on Large Language Models, arXiv:2312.14197. The Gandalf data is described in Pfister et al.,
Gandalf the Red, arXiv:2501.07927. The deepset set has no paper; its card is the reference.

What these rows are, by category (described, not reproduced here):

- `deepset`: short direct prompts labelled as injections. About half are German translations of
  the English ones. Several are role-play or task prompts ("act as an interviewer", "translate to
  polish") that are labelled injection by the dataset but carry no override at all; they were
  kept, because dropping rows after seeing them would bias the number. A few rows contain
  offensive role-play prompts; they appear in the miss table as excerpts.
- `gandalf`: player attempts to make a password-guarding chatbot reveal its password, filtered
  by the dataset authors for similarity to "ignore previous instructions". Mostly override
  phrasing with varied vocabulary.
- `bipia`: an email, table or code answer with an attack sentence inserted at the start, middle
  or end. Attack categories are task-irrelevant tasks, task-relevant output changes (reply
  backwards, reply in German), targeted misinformation, and code-injection snippets.
- `nemotron`: instructions hidden in the record a tool returns (chart notes, order fields, case
  notes), asking the agent to take an action it was not asked for: send a referral, change a
  status, cancel an appointment, send data to an address.

These files keep their own licences and are not covered by the repo's MIT licence.

### Constructed attack rows: `injection_constructed.json`, 33 attacks

Instances of published attack families written for this repo. Each payload is a harmless canary
(reply BANANA, state a wrong price, send to a `collector.example` address); none asks for
anything harmful. They were written by someone who had read the gate's patterns, so recall on
them is optimistic; the results keep them in a separate row from the public rows.

| family | cases | reference key |
|---|---|---|
| override phrase in a tool result | 3 | `perez2022`, `greshake2023` |
| HTML comment, hidden element, script | 4 | `greshake2023` |
| chat template role tokens | 3 | `chatml`, `llama2`, `llama3` |
| Unicode tag character smuggling | 3 | `rehberger2024tags`, `goodside2024` |
| markdown image exfiltration (query, path, reference link) | 3 | `rehberger2023md` |
| send-to-address and raw tool-call key | 2 | `zhan2024` |
| bidi control characters | 2 | `boucher2021` |
| zero-width character inside a keyword | 1 | `boucher2022` |
| base64, rot13, leetspeak, spaced letters, split across fields | 5 | `kang2023` |
| other languages (French, Spanish, Persian) | 3 | `yong2023` |
| persuasion written as data | 2 | `nestaas2024` |
| paraphrased override | 2 | `perez2022` |

### Constructed benign rows: `injection_constructed.json`, 81 cases

Ordinary text chosen because it looks suspicious to a marker list: security writing that quotes
attacks, hiring and support emails with an address, image CDN URLs with size parameters, prompt
format documentation, XML with `<system>` tags, API docs mentioning `tool_calls`, everyday uses of
"ignore the previous message", manuals with "new instructions:", Persian text with zero-width
non-joiners, emoji sequences, right-to-left names wrapped in bidi isolates, and files joined with
a byte-order mark in the middle. Because they were chosen to be hard, the false-reject rate on
them is an upper-end stress number, not the rate on typical tool output.

### References

- `perez2022`: Fabio Perez, Ian Ribeiro. Ignore Previous Prompt: Attack Techniques For Language Models. NeurIPS ML Safety Workshop 2022. arXiv:2211.09527.
- `greshake2023`: Kai Greshake et al. Not what you've signed up for: Compromising Real-World LLM-Integrated Applications with Indirect Prompt Injection. AISec 2023. arXiv:2302.12173.
- `chatml`: OpenAI. Chat Markup Language (ChatML) format notes, openai-python repository, 2023.
- `llama2`: Hugo Touvron et al. Llama 2: Open Foundation and Fine-Tuned Chat Models. arXiv:2307.09288; and Meta's `[INST]` / `<<SYS>>` prompt format.
- `llama3`: Meta. Llama 3 model card and prompt format (`<|start_header_id|>`, `<|eot_id|>`), 2024.
- `rehberger2024tags`: Johann Rehberger. ASCII Smuggler Tool: Crafting Invisible Text and Decoding Hidden Codes. embracethered.com, January 2024.
- `goodside2024`: Riley Goodside. Posts on X demonstrating instructions hidden in Unicode tag characters, January 2024.
- `rehberger2023md`: Johann Rehberger. Write-ups on data exfiltration through auto-loaded markdown images in chat assistants (Bing Chat, ChatGPT plugins). embracethered.com, 2023.
- `zhan2024`: Qiusi Zhan et al. InjecAgent: Benchmarking Indirect Prompt Injections in Tool-Integrated Large Language Model Agents. Findings of ACL 2024. arXiv:2403.02691.
- `boucher2021`: Nicholas Boucher, Ross Anderson. Trojan Source: Invisible Vulnerabilities. USENIX Security 2023. arXiv:2111.00169.
- `boucher2022`: Nicholas Boucher, Ilia Shumailov, Ross Anderson, Nicolas Papernot. Bad Characters: Imperceptible NLP Attacks. IEEE S&P 2022. arXiv:2106.09898.
- `kang2023`: Daniel Kang et al. Exploiting Programmatic Behavior of LLMs: Dual-Use Through Standard Security Attacks. arXiv:2302.05733.
- `yong2023`: Zheng-Xin Yong, Cristina Menghini, Stephen H. Bach. Low-Resource Languages Jailbreak GPT-4. arXiv:2310.02446.
- `nestaas2024`: Fredrik Nestaas, Edoardo Debenedetti, Florian Tramer. Adversarial Search Engine Optimization for Large Language Models. arXiv:2406.18382.

## Findings that look like bugs

Neither is fixed in this change; gate behaviour is unchanged.

1. `ground._NUMBER` has a left boundary and no right boundary, so "2P", "4K" or "1900s" in a claim
   yields the number 2, 4 or 1900, and that number must then appear in the quote. The module
   docstring says the check is on "standalone" numbers, and the same docstring relies on "A2" not
   being one. In this corpus it causes 2 false rejects (P01-1, P01-2) and is the only reason 2
   unsupported claims are rejected (P01-4, vitaminc-53302). The CHANGELOG entry of 2026-10-16
   already notes the "2P" case.
2. `injection_gate._ZERO_WIDTH` contains U+200C (zero-width non-joiner). Persian, Urdu and
   Kurdish spelling uses it inside ordinary words, so every Persian text in the benign set that
   contains one is flagged as `invisible` (benign-55, 56, 58). The module already leaves out U+200D
   for the same reason with emoji. The one Persian attack in the corpus (cons-29) is flagged only
   because of this character, not because of its content.

## What this evaluation does not cover

- It is small: 320 grounding cases and 204 injection cases. The intervals in the results are
  wide, and most per-type rows have fewer than 25 items.
- 260 of the 320 grounding cases, 33 attacks and all 81 benign cases were written by one person
  who had read the gates' code. No second annotator checked the labels, and there is no
  inter-annotator agreement number.
- The grounding cases always supply a quote. The gate's real input comes from a model that picks
  its own quote; how often a model picks a quote that is not in the source, or a misleading one,
  is not measured here.
- No case is in a language other than English for grounding. For injection, the public rows
  include German and the constructed rows include French, Spanish and Persian; nothing else.
- Injection cases are single strings. Attacks split across several tool calls or pages, images,
  PDFs and audio are not covered, and neither is whether a flagged item would have changed a
  model's behaviour.
- The honesty gate and the eligibility gate are not measured here. The honesty gate's duration
  check compares against `date.today()`, so its verdicts move with the clock and a committed
  result would go stale; the eligibility gate depends on `GRAD_YEAR`. Both still have only their
  unit tests.
