# Architecture notes: building a personal system with an AI coding agent in the loop

This repo is a small, deliberately incomplete extract of a larger personal "life-operating-system"
project: files plus a coding agent (Claude Code) that reads and writes them across long-running,
multi-session work. Most of that system is personal and stays private. What is worth publishing
is the handful of ideas that made the agent trustworthy enough to run semi-autonomously, and two
working pieces of code (`honesty_gate.py`, `eligibility_gate.py`) that are concrete instances of
those ideas, not just descriptions of them.

None of this is novel research. It is a plain writeup of what actually held up after months of
running an agent against real, high-stakes personal work (a job search, in this case), and what
broke before it held up.

## 1. The file-brain: source of truth lives in files, not in a chat transcript

An agent's context window is not memory, it is a cache. Anything that matters has to live in a
file the agent reads at the start of a session, not in the scrollback of a conversation that will
eventually be compacted or dropped. So the design commits to one rule: if a fact, decision, or
piece of state is going to matter next session, it goes in a file, immediately, in the file that
already owns that kind of fact. Not a new file "for now." Not a note to self in the chat. A write
to the canonical location.

The payoff: a new session (or a different agent, or a human) can reconstruct full context by
reading a short, known set of files, instead of needing the conversation history that produced
them. This is also what makes an agent's work auditable after the fact: you can diff the files,
not re-read a transcript.

## 2. One writer per file, for concurrent agents

Once more than one agent (or more than one machine) can touch the same repo, the naive approach
(both write, hope for the best) produces silent data loss: agent A reads a file, agent B writes a
different version, agent A writes back its stale copy and clobbers B's change. The fix is not a
distributed lock; it is a much simpler convention: assign every file (or every well-scoped
directory) exactly one writer, and make every other agent read-only for it. Two agents can safely
read the same file in parallel. Only one may ever write it. When a task genuinely needs a second
writer, that is a sign the file's scope is wrong, not that the rule needs an exception.

This rule is cheap to state and easy to violate by accident (a helper script, a background job, a
second agent instance spun up for "just this one fix"). It is worth a comment at the top of any
file that is genuinely shared, naming its one writer.

## 3. Machine-checkable agent contracts, not prompt instructions

The single biggest lesson in this repo: **a rule an agent is told in a prompt gets forgotten,
paraphrased, or silently deprioritized under context pressure. A rule enforced by code does not.**

`honesty_gate.py` and `eligibility_gate.py` are both examples of turning a policy ("do not
fabricate experience," "do not queue a role class this applicant cannot hold") into a function
that returns a verdict, not a suggestion left for the model to remember. The generation pipeline
these gates were built for calls `check()`/`is_eligible()` and rejects on any violation,
mechanically, every time, regardless of how long the session has been running or how the prompt
was worded that day.

The `tools/engine/ground.py` substring-validation gate is the same idea applied to a different
problem: instead of trusting a (possibly free/weak) model not to hallucinate a fact from a
scraped web page, the code demands a verbatim quote and checks the quote is actually present in
the source text. A model cannot talk its way past a `str in str` check. This is the general
pattern: **wherever a failure mode can be phrased as a checkable postcondition, write the check in
code and make it mandatory, instead of asking the model to please remember not to do the bad
thing.**

The same honesty applies to its limits (see `ground.py`'s docstring and `tools/engine/tests/`): a
present quote is necessary evidence, not sufficient proof. The check proves the quote appears in the
source, not that the quote supports the claim, so a real quote pasted next to a false claim still
passes. It makes inventing a fact from nothing hard; it does not make misattributing a real quote
hard. That is the grounding-gate analogue of `honesty_gate.py`'s "real term in a false context".

## 4. Adversarial verification: default to refuting, not confirming

A model reviewing its own work (or another model's work) has an incentive gradient toward
agreement: confirming "looks good" is the path of least resistance, and a model does not feel the
cost of a false "pass" the way a human reviewer eventually does. The fix that held up in practice
was to explicitly instruct any reviewing step to try to find the failure, not to check whether the
work looks plausible. Concretely, this shows up as: state the specific way this could be wrong
before evaluating; require a reviewer to cite the exact evidence for a pass, not just assert one;
and treat "I could not find a problem" as a weaker claim than "here is why this specific claim is
supported."

`honesty_gate.py`'s "WHAT THIS GATE CANNOT CATCH" section is this principle applied to itself: the
gate does not just check for known-bad patterns, it documents, out loud, the fabrication classes
it is structurally unable to catch (true words in a false context, seniority inflation, a claim
that fits inside the record but is still not the real number). A verification step that hides its
own blind spots is worse than no verification step, because it launders the reader's trust.

## 5. Human gates on irreversible actions

Autonomy should scale with reversibility, not with how boring or repetitive the task is. The
practical rule: an agent can act freely (create, edit, delete drafts, run local commands, iterate)
right up until an action would be expensive or impossible to undo (spend money, send an
irreversible communication, deploy to production, publish something to the outside world,
rewrite shared history). Those actions get a single, clearly-named human approval gate, and
everything upstream of that gate is prepared as completely as possible so the human's part of the
job is one small, well-informed decision, not a blank prompt.

The engine described in `tools/engine/README.md` follows this directly: its terminal action is a
notification or a written brief, never an auto-purchase or an auto-message to a third party. The
gate is not "ask permission for everything," which trains a human to rubber-stamp; it is "act
freely everywhere reversible, and make the few irreversible moments impossible to miss."

## 6. The failure-mode ledger

Every real failure gets turned into a generalized rule, written down, and consulted before similar
work starts again, rather than re-learned by feel each time. The discipline that matters is not
the specific list of past mistakes (those are project-specific and usually not interesting to a
stranger) but the shape: for each failure, name the *class* of mistake (not just the instance), the
root cause, and the concrete rule that would have prevented the whole class, not just that one
occurrence. A ledger that only records "fixed bug #47" teaches nothing next time a similar bug
shows up in a different disguise; a ledger that records "any gate that reads a subset of fields is
a partial gate, always enumerate the fields explicitly" prevents the whole family.

Two entries from the ledger this repo was extracted from, generalized:

- **A gate that checks some of the relevant fields is a false sense of security, not partial
  coverage.** `honesty_gate.py` originally scanned the summary and bullets but not the cover
  letter; the fix was not "also check the cover letter," it was "enumerate every field a human
  will read, explicitly, so a new field can never be silently unscanned again" (`_fields_of()`).
- **A scoring/ranking heuristic and a hard eligibility gate must never live in the same function
  with different owners.** The bug `eligibility_gate.py` was built to fix was a *scoring* module
  giving bonus points to exactly the role classes a *gating* rule should have hard-blocked. Once
  eligibility became its own module with its own tests, every scorer and sourcer could import it
  instead of re-implementing (and re-breaking) the same judgment.

## What this repo does not include, and why

This is an extract, not a mirror. Left out on purpose: anything tied to one person's real job
search, resume, transcript, or finances; the orchestration layer that wires the gates above into
a full apply pipeline; and the personal config (target lists, contact info, real credentials) that
made the source project specific to one person's life. What is here is the part that generalizes:
two working, tested gates, a small intake-engine spine, a free-model router, and this writeup.
