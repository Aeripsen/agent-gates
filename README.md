# agent-gates

Machine-checkable gates for LLM agents: an honesty gate that keeps a generated resume from
vouching for itself, an eligibility gate that blocks job classes a student applicant cannot be
hired into, and a grounding gate that makes even weak free models safe for web extraction
because a claim without a verbatim found-in-source quote is dropped by code, not by judgment.

This is a small, hand-picked extract of a private personal automation project. The full project is a
"life-operating-system" repo: a job search pipeline, a buying/research agent, a calendar and
habits system, and a lot of personal data that will never be public. This repo is not that. It is
the few pieces that are actually general enough to be useful or interesting to someone else, with
every trace of the original owner's personal data removed and replaced by a synthetic example.

If you are looking for a polished framework, this is not it. If you want two small, tested, honest
pieces of code plus a writeup of what made an AI coding agent trustworthy enough to run against
real personal stakes, that is what is here.

## What is actually in this repo

- **`projects/job-search/src/honesty_gate.py`** - validates AI-generated resume/cover-letter text
  against an evidence corpus that is deliberately split from the resume's own claims (so the
  resume can never vouch for itself). Also checks duration claims against real role date ranges,
  and flags generic filler openings. See the "what this cannot catch" section below and the full
  module docstring; it is the most interesting piece here precisely because of what it admits it
  cannot do.
- **`projects/job-search/src/eligibility_gate.py`** - classifies a job title into
  `INTERN_COOP` / `NEW_GRAD` / `FULL_TIME` / `UNCLEAR` so a student applicant never gets queued for
  a role class they cannot actually be hired into. Built after a real scoring bug was found giving
  bonus points to exactly the role classes that auto-reject a student.
- **`projects/job-search/tests/`** - the tests for both gates, including real regression cases
  (title patterns and fabrication strings that actually broke a real pipeline once). Everything
  the tests read is synthetic example data for a fictional applicant, not real personal data.
- **`tools/llm_router.py`** - a free-tier LLM router with a provider fallback chain (OpenRouter,
  Groq, Gemini), so bulk/cheap text work does not need a paid API budget.
- **`tools/engine/`** - a small "discover, fetch, sanitize, ground, store, alert" intake-engine
  skeleton, including a substring-based grounding gate that makes it safe to let even a weak free
  model extract facts from scraped web content: a claim without a verbatim, found-in-source quote
  is dropped by code, not by the model's judgment.
- **`ARCHITECTURE.md`** - the ideas that generalize: file-brain-as-source-of-truth, one writer per
  file for concurrent agents, machine-checkable agent contracts instead of prompt instructions,
  adversarial verification, human gates on irreversible actions, and a failure-mode ledger
  discipline.

## What this repo does NOT do

- It is not a full job-application pipeline. The orchestration that queues, tailors, and submits
  applications end to end is not here; it was tightly coupled to one person's real resume,
  credentials, and job-tracking data, and stripping it to be safely generic would have left
  nothing real behind.
- It is not a ready-to-run scraping/monitoring bot. `tools/engine/` is the reusable spine
  (sanitize, ground, store, alert, two example adapters), not a wired-up product; see
  `tools/engine/README.md` for exactly what is and is not included.
- It does not contain any real resume, any real job-application history, any real company names
  the original author applied to, any transcript or GPA, any citizenship/work-authorization
  answers, or any credentials. Every example in `projects/job-search/data/` is synthetic, for a
  fictional applicant, written specifically so the tests can run standalone.
- The honesty gate is not a lie detector. Read the next section before trusting a "pass" from it.

## The honesty gate's own documented limitation (quoted, not summarized)

This is the part of `honesty_gate.py`'s module docstring that matters most, verbatim:

> WHAT THIS GATE CANNOT CATCH. Read this before trusting a pass.
>
> A static term-presence check is a keyword filter. It has no model of truth, and these classes
> get through it. A pass means "no known-bad token", never "this is true":
>
> - A REAL TERM IN A FALSE CONTEXT. The single most dangerous class, and structurally
>   uncatchable here. "Building and training large language models" is caught today only because
>   the literal phrase is corpus-absent; "trained models on 1M+ records" would pass, because every
>   token is real and only the claim is false. Rearranged truth is invisible to a bag-of-words
>   check.
> - A DURATION THAT FITS INSIDE THE RECORD. "Over 8 months of experience" is not provably false
>   when a 17-month role exists, even if the real figure is different. Only claims that exceed the
>   whole record are decidable from dates alone; anything smaller is unfalsifiable here.
> - SENIORITY / SCOPE / OWNERSHIP INFLATION. "Led", "architected", "owned", "at scale", "in
>   production" attach to real work and are pure judgment.
> - QUANTITIES. "Improved performance 40%", "10M requests/day". No number in a generation is
>   checked against anything except duration claims.
> - A SKILLS-LINE TERM WITH NO EVIDENCE. Whatever the applicant lists on the Skills line with
>   nothing behind it in evidence is NOT in RISK_VOCAB, so a bullet claiming shipped work in it
>   passes. That is a deliberate open question for the applicant to resolve, not something this
>   gate silently decides for them.
>
> The gate is a floor, not a guarantee. It catches the dumb, repeatable fabrications so a human
> can spend attention on the ones that need judgment. Do not report "honesty gate: pass" as if it
> means the content is true.

If a tool like this cannot tell you "this is true," it is fair to ask what it is for. The honest
answer: it catches a specific, real, repeatable failure mode (a model mirroring a job description
back at you and inventing a stack or a domain you never worked in, or padding a duration claim
past what your actual dates support), cheaply and deterministically, so a human reviewer's
attention goes to the harder judgment calls instead of re-checking the same dumb mistakes every
time.

## Running the tests

```
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install pytest
python -m pytest projects/job-search/tests -q
```

## Setup for the tools that need keys

Copy `.env.example` to `.env` and fill in your own free-tier API keys (OpenRouter, Groq, Gemini,
Brave Search, Telegram bot token) if you want to run `tools/llm_router.py` or `tools/engine/`.
Neither gate under `projects/job-search/` needs any key or network access; both are pure,
offline, stdlib-only Python.

## License

MIT. See `LICENSE`.
