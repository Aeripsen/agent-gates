#!/usr/bin/env python3
"""Pre-queue eligibility gate: block role classes a student applicant cannot be hired into.

Configure GRAD_YEAR (env var, default below) to the year you expect to graduate / become
available full-time. While that year is in the future, two role classes auto-reject you no
matter how good the resume is:

  NEW_GRAD   - "New Grad", "Recent Graduate", "Graduate Program", "Early Career". These want
               someone graduating in the next admissions cycle; a graduation year further out is
               outside every real window.
  FULL_TIME  - a career req with no student lane: bare "Software Engineer", "Data Scientist",
               "Product Analyst", plus level markers (Junior, Associate, I/II/III, "all levels",
               Senior+). Not available full-time yet.

Only INTERN_COOP (intern / co-op / internship / student / work-term / summer-analyst) is a class
you can actually be hired into today. UNCLEAR means the title carries no class signal; it passes
the gate on purpose (a gate that guesses would silently drop real roles) and stays for human
review.

Why this exists: an audit of a real submission log (built while extracting this gate from a
larger pipeline) found that roughly half of the auto-rejected submissions were NEW_GRAD or
FULL_TIME reqs, and the scoring code upstream was not neutral about it, it was actively wrong:
one scorer gave "new grad"/"entry level"/"associate" a flat bonus, and another sourcing module
flagged "new grad"/"graduate program" titles as an intern-equivalent match - i.e. the two classes
that auto-reject a student were being ranked as the student's BEST matches. This gate is the fix:
a single source of truth for "can this applicant actually be hired into this role", imported by
every path that can source, queue, or submit a role.

Title-level signals only (cheap, high precision, no HTTP). Callers holding a real job description
may pass jd=... to catch an explicit graduation window ("class of 2026", "graduating by Summer
2026"); the JD is otherwise ignored because JD boilerplate is noisy.

Usage:
  from eligibility_gate import is_eligible, classify, skip_note
  if not is_eligible(title): ...            # in every queue/apply path (mandatory gate)
  python eligibility_gate.py                # batch-scan data/tracker.csv, print the breakdown
  python eligibility_gate.py --purge        # mark status=new ineligible rows status=skip
  python eligibility_gate.py --purge --dry-run
"""
from __future__ import annotations
import argparse
import csv
import os
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_TRACKER = _ROOT / "projects" / "job-search" / "data" / "tracker.csv"

# The example applicant's expected graduation year. In this repo it matches the synthetic
# data/applicant_profile.yaml so the tests are consistent; override via the GRAD_YEAR env var
# for your own use, or just edit the constant.
GRAD_YEAR = int(os.environ.get("GRAD_YEAR", "2027"))

INTERN_COOP = "INTERN_COOP"
NEW_GRAD = "NEW_GRAD"
FULL_TIME = "FULL_TIME"
UNCLEAR = "UNCLEAR"

INELIGIBLE_CLASSES = frozenset({NEW_GRAD, FULL_TIME})

# 1. Student-lane words. Highest precedence: a req that says "intern" anywhere has an intern lane,
#    even when it also says "campus" or "full-time" (some employers post BOTH "Campus Software
#    Engineer (Intern)" and "Campus Software Engineer (Full-Time)" as separate reqs - the suffix
#    is the whole signal, which is also why "campus" is NOT a new-grad marker below).
INTERN_MARKERS = [
    r"\binterns?\b", r"\binternships?\b", r"\bco-?ops?\b", r"\bco op\b",
    r"\bstudents?\b", r"\bapprentice(?:ship)?s?\b", r"\bplacements?\b",
    r"\bwork[- ]?term\b", r"\bsummer analyst\b", r"\bsummer associate\b",
    r"\bpraktikum\b", r"\bstage\b",
]

# 2. New-grad program words. Every one of these targets a graduation window that closes before
#    GRAD_YEAR.
NEW_GRAD_MARKERS = [
    r"\bnew[- ]?grads?\b", r"\bnew graduates?\b", r"\brecent grads?\b", r"\brecent graduates?\b",
    r"\bgraduate program(?:me)?\b", r"\bgrad program(?:me)?\b", r"\bgraduate scheme\b",
    r"\bearly[- ]?career\b", r"\buniversity grads?\b", r"\buniversity graduates?\b",
    r"\bcampus hire\b", r"\brotational program(?:me)?\b", r"\bleadership program(?:me)?\b",
    r"\bgraduate (?:software|research|machine|data|analyst)\b",  # "Graduate Software Engineer"
    r"\bclass of 20\d\d\b",
]

# 3. Full-time level markers. A level implies a career req with no student lane.
FULL_TIME_MARKERS = [
    r"\bjunior\b", r"\bjr\.?\b",
    r"\bassociate\b",
    r"\bentry[- ]?level\b",
    r"\ball levels\b",
    r"\bfull[- ]?time\b",
    r"\bsenior\b", r"\bsr\.?\b", r"\bstaff\b", r"\bprincipal\b", r"\bdistinguished\b",
    r"\bhead of\b", r"\bdirector\b", r"\bvice president\b", r"\bvp\b",
    # level suffix: "Software Engineer I", "Data Scientist II", "Analyst III". The \b after the
    # numeral keeps "Engineer, Infrastructure" and "Engineer Intern" from matching a bare "I".
    # The en/em dashes in the class are DATA, not prose: real ATS titles use them as separators
    # ("Quantitative Trader - 2027 Graduate Program"). Removing them silently breaks those titles.
    r"\b(?:engineer|developer|scientist|analyst|architect|designer|programmer|specialist"
    r"|consultant|manager|associate)\s*[-,–—]?\s*(?:i{1,3}|iv|v)\b",
]

# 4. Weak intern signals, for reqs that never say "intern" but describe an intern term:
#    a season+year cohort ("Software Engineer (Summer 2027)", "... - 2026 Summer") or a
#    co-op term length ("... Developer - AI Innovation (4 mo)" is a real co-op with no intern word
#    in the title). Season and year appear in both orders across real postings.
#    Checked AFTER 2 and 3 on purpose - some employers post "Software Engineer I, Entry-Level
#    (Graduation Date: Fall 2025-Summer 2026)", where the season+year is a graduation window, not
#    an intern term.
TERM_MARKERS = [
    r"\b(?:summer|fall|autumn|winter|spring)\s*20\d\d\b",
    r"\b20\d\d\s*(?:summer|fall|autumn|winter|spring)\b",
    r"\b(?:4|8|12|16)[- ]?(?:mo|mos|months?)\b",
]

# 5. Career-role nouns. A req titled with one of these and NO student marker is a full-time job.
#    This is the rule that catches the confirmed-rejected bare titles ("SWE, Security",
#    "Data Scientist", "Software Engineer", "Product Engineer").
CAREER_ROLE_MARKERS = [
    r"\bsoftware (?:engineer(?:ing)?|develop(?:er|ment|ment engineer))\b", r"\bswe\b", r"\bsde\b",
    r"\b(?:back|front)[- ]?end (?:engineer|developer)\b", r"\bfull[- ]?stack\b",
    r"\bweb developer\b", r"\bmobile (?:engineer|developer)\b",
    r"\bdata (?:scientist|analyst|engineer)\b", r"\bdata science\b",
    r"\bmachine learning\b", r"\bml engineer\b", r"\bmle\b", r"\bai engineer\b",
    r"\bapplied (?:scientist|ai)\b", r"\bresearch (?:engineer|scientist|assistant)\b",
    r"\bsecurity (?:engineer|analyst|architect)\b", r"\bsecurity researcher\b",
    r"\bsolutions? (?:engineer|architect)\b", r"\bsales engineer\b",
    r"\bsite reliability\b", r"\bsre\b", r"\bdevops\b", r"\bplatform engineer\b",
    r"\binfrastructure engineer\b", r"\bsystems? engineer\b", r"\bnetwork engineer\b",
    r"\bembedded (?:engineer|software)\b", r"\bfirmware\b", r"\bhardware engineer\b",
    r"\bquantitative (?:researcher|trader|developer|analyst)\b", r"\bquant\b",
    r"\bproduct (?:engineer|analyst|manager|designer)\b",
    r"\bprogram manager\b", r"\bproject manager\b", r"\bbusiness analyst\b",
    r"\bforward deployed\b", r"\bdeveloper relations\b", r"\bdeveloper advocate\b",
    r"\btechnical program\b", r"\bengineering manager\b",
    # bare role nouns, last: by here the title has no student lane and no level, so a req named
    # for the job itself ("Developer", "Developer Experience Engineer") is a career posting.
    r"\bengineers?\b", r"\bdevelopers?\b", r"\bscientists?\b", r"\banalysts?\b",
    r"\bresearchers?\b", r"\barchitects?\b", r"\bprogrammers?\b",
]

# JD-only: an explicit graduation window. High precision, so it is safe to read from JD text.
GRAD_WINDOW = [
    r"\bclass of 20\d\d\b",
    r"\bgraduat\w*\s+(?:in|by|between|before)\s+(?:\w+\s+)?20\d\d\b",
    r"\bgraduation date\b",
    r"\b(?:must|should)\s+graduate\b",
]


def _hit(patterns: list[str], text: str) -> str | None:
    """Return the matched text of the first pattern that fires, else None."""
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(0).strip()
    return None


def _grad_window_excludes(jd: str) -> str | None:
    """A JD graduation window that cannot include GRAD_YEAR. Only fires when the JD names years and
    every named year is before GRAD_YEAR, so an open-ended or GRAD_YEAR+ window never trips it."""
    low = jd.lower()
    if not _hit(GRAD_WINDOW, low):
        return None
    years = [int(y) for y in re.findall(r"\b(20[2-3]\d)\b", low)]
    if years and max(years) < GRAD_YEAR:
        return f"jd graduation window {min(years)}-{max(years)}"
    return None


def classify(title: str, jd: str = "") -> tuple[str, str]:
    """Classify a role into INTERN_COOP / NEW_GRAD / FULL_TIME / UNCLEAR.

    Returns (klass, marker) where marker is the token that decided it (empty for UNCLEAR).
    Precedence is deliberate and load-bearing; see the numbered comments on the marker lists.
    """
    low = f" {(title or '').lower()} "

    m = _hit(INTERN_MARKERS, low)
    if m:
        return INTERN_COOP, m

    m = _hit(NEW_GRAD_MARKERS, low)
    if m:
        return NEW_GRAD, m

    m = _hit(FULL_TIME_MARKERS, low)
    if m:
        return FULL_TIME, m

    if jd:
        m = _grad_window_excludes(jd)
        if m:
            return NEW_GRAD, m

    m = _hit(TERM_MARKERS, low)
    if m:
        return INTERN_COOP, m

    m = _hit(CAREER_ROLE_MARKERS, low)
    if m:
        return FULL_TIME, m

    return UNCLEAR, ""


def is_eligible(title: str, jd: str = "") -> bool:
    """False only for a class the applicant is structurally ineligible for. UNCLEAR passes (see
    module docstring)."""
    return classify(title, jd)[0] not in INELIGIBLE_CLASSES


def skip_note(title: str, jd: str = "") -> str:
    """The tracker notes string for an ineligible row. Empty when the role passes the gate."""
    klass, _ = classify(title, jd)
    if klass not in INELIGIBLE_CLASSES:
        return ""
    return f"ineligible: grad {GRAD_YEAR}, role is {klass}"


def _norm_url(u: str) -> str:
    """Tracker URLs and apply URLs differ by a trailing /application and a query string."""
    u = (u or "").split("?")[0].strip().lower().rstrip("/")
    if u.endswith("/application"):
        u = u[: -len("/application")]
    return u


def title_for_url(url: str) -> str | None:
    """The tracker title for an apply URL, or None if the URL is not in the tracker."""
    if not _TRACKER.exists():
        return None
    key = _norm_url(url)
    if not key:
        return None
    with open(_TRACKER, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if _norm_url(r.get("url", "")) == key:
                return r.get("title", "")
    return None


def check_url(url: str) -> tuple[str, str] | None:
    """Backstop for the apply lane, which only has a URL. Returns (klass, marker) when the tracker
    says this URL is an ineligible class, else None. A URL absent from the tracker returns None
    (cannot classify without a title); the caller is expected to say so out loud rather than
    pretend the gate ran."""
    title = title_for_url(url)
    if title is None:
        return None
    klass, marker = classify(title)
    return (klass, marker) if klass in INELIGIBLE_CLASSES else None


def filter_rows(rows, title_key="title", log=True, label="rows"):
    """Drop ineligible rows from a queue/apply candidate list. Failures are visible, never silent:
    prints what it dropped and why, so a shrinking queue is always explained."""
    kept, dropped = [], Counter()
    for r in rows:
        klass, marker = classify(r.get(title_key, "") or "")
        if klass in INELIGIBLE_CLASSES:
            dropped[klass] += 1
            continue
        kept.append(r)
    if log and dropped:
        total = sum(dropped.values())
        detail = ", ".join(f"{k}={v}" for k, v in dropped.most_common())
        print(f"[eligibility_gate] dropped {total} ineligible {label} ({detail}); "
              f"grad {GRAD_YEAR} -> intern/co-op only")
    return kept


def _scan_tracker():
    if not _TRACKER.exists():
        print(f"no tracker at {_TRACKER}")
        return
    rows = list(csv.DictReader(open(_TRACKER, encoding="utf-8")))
    by_status = Counter()
    counts = Counter()
    examples = {}
    for r in rows:
        klass, marker = classify(r.get("title", ""))
        counts[klass] += 1
        by_status[(r.get("status", ""), klass)] += 1
        examples.setdefault(klass, []).append(f"{r.get('company','?')} | {r.get('title','')[:60]}")
    print(f"scanned {len(rows)} tracker rows\n")
    for klass in (INTERN_COOP, NEW_GRAD, FULL_TIME, UNCLEAR):
        flag = "ELIGIBLE" if klass not in INELIGIBLE_CLASSES else "INELIGIBLE"
        print(f"{klass:12} {counts[klass]:5}  [{flag}]")
        for e in examples.get(klass, [])[:3]:
            print(f"             e.g. {e}")
    new_inelig = sum(v for (st, kl), v in by_status.items()
                     if st == "new" and kl in INELIGIBLE_CLASSES)
    print(f"\nstatus=new AND ineligible: {new_inelig} (these are the leak)")


def _repair_split_notes(rows: list[dict], fields: list[str]) -> int:
    """Rejoin a notes cell that was written to tracker.csv unquoted and split on its own comma.

    A notes cell like "... found in inbox reconcile, tracker was stale" written WITHOUT csv
    quoting makes the comma a 19th field on an 18-field table, and csv.DictReader parks the tail
    under key None. Rejoining with the comma restores the note byte for byte, and DictWriter
    quotes it on the way out, so a row repaired once stays repaired. Lossless: no cell is dropped.
    """
    n = 0
    last = fields[-1] if fields else "notes"
    for r in rows:
        extra = r.pop(None, None)
        if not extra:
            continue
        tail = ",".join(x for x in extra if x is not None)
        r[last] = f"{(r.get(last) or '')},{tail}"
        n += 1
    if n:
        print(f"repaired {n} row(s) whose '{last}' cell was written unquoted and split on a comma")
    return n


def _purge_tracker(dry_run: bool = False):
    """Mark every status=new row that the gate calls ineligible as status=skip, with the reason in
    notes. INTERN_COOP and UNCLEAR rows are never touched.

    tracker.csv has no single-writer guarantee if other processes rewrite it, so this reads fresh,
    edits in memory, and writes ONCE via an atomic replace instead of holding the file open.
    Existing notes are preserved (appended to) - the old note is often the only record of why a
    row was sourced.
    """
    rows = list(csv.DictReader(open(_TRACKER, encoding="utf-8")))
    fields = [f for f in (rows[0].keys() if rows else []) if f is not None]
    repaired = _repair_split_notes(rows, fields)
    counts = Counter()
    for r in rows:
        if r.get("status") != "new":
            continue
        klass, _marker = classify(r.get("title", ""))
        if klass not in INELIGIBLE_CLASSES:
            continue
        counts[klass] += 1
        if not dry_run:
            r["status"] = "skip"
            note = skip_note(r.get("title", ""))
            prev = (r.get("notes") or "").strip()
            r["notes"] = f"{prev} | {note}".strip(" |") if prev else note
            r["next_action"] = "none - ineligible class"
    total = sum(counts.values())
    print(f"purge: {total} status=new rows -> skip  ({dict(counts)})")
    if dry_run:
        print("(dry run) nothing written.")
        return counts
    # atomic write: temp file in the same dir, then os.replace
    fd, tmp = tempfile.mkstemp(dir=str(_TRACKER.parent), suffix=".tmp")
    os.close(fd)
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, _TRACKER)
    print(f"wrote {_TRACKER} ({len(rows)} rows, single atomic write)")
    return counts


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--purge", action="store_true",
                    help="mark ineligible status=new rows status=skip in tracker.csv")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.purge:
        _purge_tracker(dry_run=a.dry_run)
    else:
        _scan_tracker()
