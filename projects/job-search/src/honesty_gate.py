#!/usr/bin/env python3
"""Post-generation honesty gate for tailored resume / cover-letter content.

Scans the summary, every tailored_bullet, AND the cover letter. (In the project this gate was
extracted from, the cover letter went unscanned for a while after the summary/bullet checks were
first built, which is exactly how a fabrication slips through: a gate that checks two of three
fields reports "pass" while the third field carries the lie.)

Three checks, all static, all cheap, no HTTP:

  1. RISK_VOCAB   - a framework / product / tool / work-domain named in the generation but absent
                    from the EVIDENCE corpus. The confirmed fabrication class: a model mirroring a
                    job description invents a stack the applicant never used (e.g. inventing a PHP
                    framework onto a plain HTML/CSS/JS site, or a finance-domain project onto an
                    unrelated research role).
  2. DURATION     - "N years/months of experience" that the applicant's real experience.tex date
                    ranges cannot support. Only fires when the claim EXCEEDS the whole record (see
                    below).
  3. FILLER       - generic openings ("Highly motivated and detail-oriented ...") that say nothing
                    and read as machine-written.

EVIDENCE vs CLAIMS (why skills.tex is NOT evidence)
---------------------------------------------------
The corpus is split on purpose. `skills.tex` is the resume's own Skills line: an assertion, not
proof. Grading a generated claim against it is circular, because the resume would be vouching for
itself: "React is on the skills line, therefore a bullet claiming shipped React work is supported."
So RISK_VOCAB is matched against EVIDENCE only (experience / projects / education / community /
resume_bank / build-to-true), and a term that appears ONLY on the skills line does not count as
supported. `claims_only_terms()` reports that gap.

This split can change no current verdict and still be worth having, because it closes a live
footgun: the day any RISK_VOCAB term is added to the skills line, or any skills-line term is added
to RISK_VOCAB, the old (unsplit) corpus would have silently vouched for it.

WHAT THIS GATE CANNOT CATCH. Read this before trusting a pass.
---------------------------------------------------------------
A static term-presence check is a keyword filter. It has no model of truth, and these classes get
through it. A pass means "no known-bad token", never "this is true":

  * A REAL TERM IN A FALSE CONTEXT. The single most dangerous class, and structurally uncatchable
    here. "Building and training large language models" is caught today only because the literal
    phrase is corpus-absent; "trained models on 1M+ records" would pass, because every token is
    real and only the claim is false. Rearranged truth is invisible to a bag-of-words check.
  * A DURATION THAT FITS INSIDE THE RECORD. "Over 8 months of experience" is not provably false
    when a 17-month role exists, even if the real figure is different. Only claims that exceed the
    whole record are decidable from dates alone; anything smaller is unfalsifiable here.
  * SENIORITY / SCOPE / OWNERSHIP INFLATION. "Led", "architected", "owned", "at scale", "in
    production" attach to real work and are pure judgment.
  * QUANTITIES. "Improved performance 40%", "10M requests/day". No number in a generation is
    checked against anything except duration claims.
  * A SKILLS-LINE TERM WITH NO EVIDENCE. Whatever the applicant lists on the Skills line with
    nothing behind it in evidence (`claims_only_terms()` lists these live) is NOT in RISK_VOCAB,
    so a bullet claiming shipped work in it passes. That is a deliberate open question for the
    applicant to resolve (vouch for it in build-to-true.md, or take it off the skills line), not
    something this gate silently decides for them.

The gate is a floor, not a guarantee. It catches the dumb, repeatable fabrications so a human can
spend attention on the ones that need judgment. Do not report "honesty gate: pass" as if it means
the content is true.

Usage:
  from honesty_gate import check, corpus_text          # in the tailor pipeline (mandatory gate)
  python honesty_gate.py                                # batch-scan data/applications/*/tailored.json
  python honesty_gate.py --claims-only                  # list skills-line terms with no evidence
"""
from __future__ import annotations
import json, re, sys
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_JS = _ROOT / "projects" / "job-search"
_RESUME = _JS / "data" / "resume" / "swe"

# EVIDENCE: things the applicant did, with dates, artifacts and links behind them. The only thing
# a generated claim is graded against.
_EVIDENCE_FILES = [
    _RESUME / "education.tex", _RESUME / "experience.tex",
    _RESUME / "projects.tex", _RESUME / "community.tex",
    _JS / "data" / "resume_bank.md", _JS / "data" / "build-to-true.md",
]
# CLAIMS: the resume's own Skills line. Live resume content (main.tex pulls it via \subfile), which
# is exactly why it cannot also be the evidence that validates the resume. Never used by check().
_CLAIMS_FILES = [_RESUME / "skills.tex"]

# Framework / product / tool / domain names a model can hallucinate onto a resume. Each is a
# violation ONLY when present in the generation but ABSENT from evidence (so real work never
# trips it). Edit this list for your own resume: whatever you genuinely have NOT done.
RISK_VOCAB = [
    # web frameworks this example applicant does not use (their web work is static HTML/CSS/JS)
    "laravel", "filament", "django", "flask", "rails", "ruby on rails", "php", "symfony",
    ".net", "asp.net", "c#", "angular", "vue", "svelte", "spring boot", "struts", "blazor",
    # mobile this applicant does not do
    "kotlin", "swift", "swiftui", "flutter", "react native", "android sdk", "jetpack compose",
    "objective-c", "xamarin",
    # data / enterprise products with no genuine match in this applicant's materials
    "salesforce", "apex", "visualforce", "sap", "servicenow", "workday", "oracle", "mulesoft",
    "veeva", "snowflake", "databricks", "hadoop", "hive", "scala", "cobol",
    # work domains with no genuine match in this applicant's materials
    "energy trading", "energy storage", "battery management", "market making", "market-making",
    "derivatives pricing", "high-frequency trading", "order execution", "trading signals",
    "autonomous vehicle", "self-driving", "robotics", "smart contract", "solidity", "blockchain",
    "defi", "medical device", "clinical trial", "electronic health record", "ehr",
    # infra sometimes hallucinated (flagged only if absent from evidence)
    "jenkins", "spinnaker", "ansible", "chef ", "puppet", "grafana", "prometheus", "datadog",
    # LLM *authorship* this applicant does not have: they orchestrate LLMs (a free-model router,
    # LLM APIs) but have not built or trained one, so "llm" itself is corpus-present and passes.
    # These are the build/train verbs specifically, none of which appear in evidence.
    "large language model", "foundation model", "pretrain", "pre-train", "fine-tune", "fine-tuning",
    "finetune", "transformer architecture", "training large", "model training pipeline", "rlhf",
]

# Openings that carry no information. Generic filler is not a fabrication, but it is the tell of a
# model writing from nothing, and it is what a human reader sees first.
FILLER_OPENINGS = [
    "highly motivated and detail-oriented", "highly motivated, detail-oriented",
    "detail-oriented and highly motivated", "highly motivated and passionate",
    "results-driven professional", "dynamic and motivated", "hardworking and dedicated",
    "passionate and driven", "i am a highly motivated", "as a highly motivated",
    "motivated and detail-oriented", "enthusiastic and motivated",
]

_CHECKED_FIELDS = ("summary", "tailored_bullets", "cover_letter")


def _present(term: str, text: str) -> bool:
    """True if `term` occurs in `text`. Word-boundary match for plain words; substring for terms
    with non-word chars (.net, c#, market-making) or spaces (multiword)."""
    if re.search(r"[^\w]", term):
        return term in text
    return re.search(rf"\b{re.escape(term)}\b", text) is not None


def _read(files: list[Path]) -> str:
    return " ".join(f.read_text(encoding="utf-8") for f in files if f.exists()).lower()


_evidence_cache: str | None = None
_claims_cache: str | None = None


def corpus_text() -> str:
    """The EVIDENCE corpus. Name kept for the tailor pipeline, which passes it into check()."""
    global _evidence_cache
    if _evidence_cache is None:
        _evidence_cache = _read(_EVIDENCE_FILES)
    return _evidence_cache


def claims_text() -> str:
    """The resume's own Skills line. Deliberately NOT evidence; see the module docstring."""
    global _claims_cache
    if _claims_cache is None:
        _claims_cache = _read(_CLAIMS_FILES)
    return _claims_cache


def claims_only_terms(claims: str | None = None, evidence: str | None = None) -> list[str]:
    """Skills-line terms with nothing behind them in evidence. Not violations, and not RISK_VOCAB:
    what goes on your own skills line is your call. This just makes the gap visible instead of
    letting the old corpus quietly treat the claim as its own proof.

    A rough lexical scan, so read it with judgment: a spelling variant reads as a false gap
    ("javascript" looks unevidenced only because experience.tex writes "HTML/CSS/JS"), and
    punctuated names tokenize badly ("hugging"/"face"). Signal, not verdict.

    When you vouch for a skill no shipped role documents, record it in data/build-to-true.md and
    it drops off this list - that file is evidence. Never add a term there just to silence the
    scan; that defeats the point of separating evidence from claims.

    Both texts are injectable so a test can pin the BEHAVIOUR without pinning today's real corpus,
    which legitimately changes whenever you vouch for something new.
    """
    claims = claims_text() if claims is None else claims.lower()
    ev = corpus_text() if evidence is None else evidence.lower()
    out = []
    for term in re.findall(r"[A-Za-z][A-Za-z0-9+#./-]{1,24}", claims):
        t = term.lower().strip(".")
        if len(t) < 2 or t in _SKILLS_STOPWORDS:
            continue
        if _present(t, claims) and not _present(t, ev) and t not in out:
            out.append(t)
    return out


_SKILLS_STOPWORDS = {
    "textbf", "skills", "familiar", "learning", "bi", "analytics", "competitions", "href",
    "certifications", "item", "small", "begin", "end", "itemize", "leftmargin", "label",
    "in", "id", "place", "canada", "focus", "team", "specialization", "and", "the", "ci", "cd",
}


# ---- duration claims -------------------------------------------------------------------------

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

# experience.tex writes ranges as {Feb 2025 -- Present} / {Mar 2019 -- Aug 2022}. The unicode dashes
# in the separator class are DATA (LaTeX sources use them), not prose.
_RANGE_RE = re.compile(
    r"\{([A-Za-z]{3,9})\.?\s+(\d{4})\s*(?:--|-|–|—|to)\s*"
    r"(present|(?:[A-Za-z]{3,9})\.?\s+\d{4})\}", re.I)

_WORD_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
             "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}

_DURATION_RE = re.compile(
    r"(?:(over|more than|nearly|almost|about|around|at least|upwards of)\s+)?"
    r"(\d+(?:\.\d+)?|" + "|".join(_WORD_NUM) + r")\s*\+?\s*(years?|months?)\s+of\s+"
    r"(?:[\w\-/]+\s+){0,3}?experience", re.I)

# "While I do not yet have 5+ years of experience" is an honest disclaimer, not a claim. Without
# this guard the gate would reject the candidate for admitting a gap, which is backwards.
_NEGATION = ["not yet", "do not have", "don't have", "does not have", "doesn't have", "without",
             "lack ", "lacks ", "no ", "less than", "fewer than", "short of", "while i do not"]


def _month_index(name: str, year: str) -> int:
    return int(year) * 12 + _MONTHS[name[:3].lower()]


def _experience_text() -> str:
    """Cached: check() runs inside a retry loop over many roles, so this must not re-read the file
    per call."""
    global _experience_cache
    if _experience_cache is None:
        _experience_cache = _read([_RESUME / "experience.tex"])
    return _experience_cache


_experience_cache: str | None = None


def role_spans(today: date | None = None) -> list[int]:
    """Each experience.tex role's duration in months. 'Present' resolves against `today`."""
    today = today or date.today()
    txt = _experience_text()
    spans = []
    for m in _RANGE_RE.finditer(txt):
        smon, syr, end = m.group(1), m.group(2), m.group(3).strip()
        if smon[:3].lower() not in _MONTHS:
            continue
        start = _month_index(smon, syr)
        if end.lower() == "present":
            stop = today.year * 12 + today.month
        else:
            em = re.match(r"([A-Za-z]{3,9})\.?\s+(\d{4})", end)
            if not em or em.group(1)[:3].lower() not in _MONTHS:
                continue
            stop = _month_index(em.group(1), em.group(2))
        spans.append(max(0, stop - start))
    return spans


def total_span_months(today: date | None = None) -> int:
    """Earliest start to today: the absolute ceiling any 'years of experience' claim can support."""
    today = today or date.today()
    txt = _experience_text()
    starts = []
    for m in _RANGE_RE.finditer(txt):
        if m.group(1)[:3].lower() in _MONTHS:
            starts.append(_month_index(m.group(1), m.group(2)))
    if not starts:
        return 0
    return max(0, (today.year * 12 + today.month) - min(starts))


def _is_negated(text: str, start: int) -> bool:
    return any(n in text[max(0, start - 45):start].lower() for n in _NEGATION)


def duration_claims(text: str) -> list[tuple[str, int]]:
    """[(matched phrase, claimed months), ...] for real (non-disclaimed) experience claims."""
    out = []
    for m in _DURATION_RE.finditer(text or ""):
        if _is_negated(text, m.start()):
            continue
        raw = m.group(2).lower()
        val = _WORD_NUM.get(raw, None)
        if val is None:
            try:
                val = float(raw)
            except ValueError:
                continue
        months = val * 12 if m.group(3).lower().startswith("year") else val
        out.append((" ".join(m.group(0).split()), int(round(months))))
    return out


def _duration_violations(text: str, ceiling: int) -> list[str]:
    """Only claims that EXCEED the whole record. A claim that fits inside it is not decidable from
    dates alone (module docstring), and flagging it would reject honest drafts."""
    bad = []
    for phrase, months in duration_claims(text):
        if months > ceiling:
            bad.append(f"duration:{phrase!r} claims {months}mo, record has {ceiling}mo")
    return bad


# ---- the gate --------------------------------------------------------------------------------


def _fields_of(obj: dict) -> dict[str, str]:
    """summary + every tailored_bullet + the cover letter. 'gaps' and 'jd_keywords_matched' stay
    exempt: that is where unmet requirements are supposed to be named."""
    fields = {"summary": obj.get("summary", "") or ""}
    for i, b in enumerate(obj.get("tailored_bullets", []) or []):
        fields[f"bullet{i}"] = b or ""
    fields["cover_letter"] = obj.get("cover_letter", "") or ""
    return fields


def check(obj: dict, corpus: str | None = None) -> list[tuple[str, str]]:
    """Return [(field, reason), ...]. Empty list = passes the gate.

    A pass is NOT a truth claim; see "WHAT THIS GATE CANNOT CATCH" in the module docstring.
    Only provable violations are returned, because a tailor pipeline built on this gate should
    reject and retry on any violation: a merely suspicious signal would burn quota and drop
    honest drafts.
    """
    if corpus is None:
        corpus = corpus_text()
    ceiling = total_span_months()
    violations = []
    for field, text in _fields_of(obj).items():
        if not text:
            continue
        low = text.lower()
        for term in RISK_VOCAB:
            t = term.strip()
            if _present(t, low) and not _present(t, corpus):
                violations.append((field, t))
        hits = [f for f in FILLER_OPENINGS if f in low]
        if hits:  # phrases overlap ("highly motivated and detail-oriented" contains a shorter one);
            longest = max(hits, key=len)  # report the longest once, not every substring of it
            violations.append((field, f"filler:{longest!r}"))
        for d in _duration_violations(text, ceiling):
            violations.append((field, d))
    return violations


def _scan_pool(claims_only: bool = False):
    if claims_only:
        terms = claims_only_terms()
        print("skills-line terms with NO evidence behind them "
              "(claims, not proof; not RISK_VOCAB, so the gate does not flag them):\n")
        for t in terms:
            print(f"  {t}")
        print(f"\n{len(terms)} term(s). A rough lexical scan: spelling variants show up as false "
              "gaps (\"javascript\" vs the evidence's \"HTML/CSS/JS\") and punctuated names split "
              "(\"hugging\"/\"face\"). Read it with judgment.")
        print("Deciding what stays on the Skills line is your call, not the gate's. When you "
              "vouch for a skill the corpus does not otherwise document, record it in "
              "data/build-to-true.md (your word, with the date) - that is evidence and it drops "
              "off this list. Do NOT add a term there just to silence this scan.")
        return
    apps = _JS / "data" / "applications"
    corpus = corpus_text()
    flagged = 0
    scanned = 0
    for tj in sorted(apps.glob("*/tailored.json")):
        scanned += 1
        try:
            d = json.loads(tj.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"PARSE_ERR {tj.parent.name}: {e}")
            continue
        v = check(d, corpus)
        if v:
            flagged += 1
            role = d.get("_role", {})
            print(f"FLAG {tj.parent.name} [{role.get('company','?')} | {role.get('provider','?')}]: "
                  + ", ".join(f"{f}:{t}" for f, t in v))
    print(f"\nscanned {scanned} tailored.json; {flagged} flagged by the honesty gate")
    print(f"record ceiling for duration claims: {total_span_months()} months; "
          f"role spans (months): {sorted(role_spans(), reverse=True)}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    _scan_pool(claims_only="--claims-only" in sys.argv)
