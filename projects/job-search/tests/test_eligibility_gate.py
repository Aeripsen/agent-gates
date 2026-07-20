"""The eligibility gate, tested against the title patterns that actually cause NEW_GRAD/FULL_TIME
auto-rejects in real ATS postings.

The titles in REJECTED_FOR_CLASS below are realistic ATS title patterns (the shape employers
actually post), not tied to any specific company. If one of them ever passes the gate again for
a student applicant, the leak is back.
"""
from pathlib import Path

import pytest

import eligibility_gate as eg

ROOT = Path(__file__).resolve().parents[1]

# Realistic title patterns that should classify as ineligible for a student applicant.
REJECTED_FOR_CLASS = [
    ("ML Engineer, New Grad", eg.NEW_GRAD),
    ("Software Engineer, New Grad", eg.NEW_GRAD),
    ("Software Engineer, Early Career", eg.NEW_GRAD),
    ("Software Developer - New Graduate", eg.NEW_GRAD),
    ("Graduate Software Engineer", eg.NEW_GRAD),
    ("Software Engineer, Edge", eg.FULL_TIME),
    ("Junior Site Reliability Engineer", eg.FULL_TIME),
    ("Full Stack Development", eg.FULL_TIME),
    ("Product Analyst", eg.FULL_TIME),
    ("Associate AI Engineer", eg.FULL_TIME),
    ("Software Engineer, Backend (All Levels)", eg.FULL_TIME),
    ("Software Engineer, Internal Platform", eg.FULL_TIME),
    ("Solutions Engineer", eg.FULL_TIME),
    ("Product Engineer", eg.FULL_TIME),
    ("Software Engineer, Security", eg.FULL_TIME),
    ("Full-Stack Software Engineer, Inference", eg.FULL_TIME),
    ("Data Scientist", eg.FULL_TIME),
    ("Software Engineer", eg.FULL_TIME),
    ("Software Engineer I - Java/Python/Golang", eg.FULL_TIME),
    ("Software Engineer II, Backend (Integrations)", eg.FULL_TIME),
    ("Entry Level Software Engineer", eg.FULL_TIME),
]

ELIGIBLE_TITLES = [
    "Software Engineer Intern",
    "Software Engineering Intern (Summer 2027)",
    "Applied Machine Learning Scientist Co-op/Intern (Fall 2026)",
    "Software Engineer Internship/Co-op (Summer 2026)",
    "Co-op Software Developer",
    "Data Science Co-op (Fall 2026)",
    "Student Research Assistant",
    "Embedded C/C++ Software Developer Student",
    "Software Engineer Apprentice",
    "Summer Analyst, Quantitative Research",
    "Software Engineer (Summer 2027)",
]


@pytest.mark.parametrize("title,klass", REJECTED_FOR_CLASS)
def test_ineligible_classes_are_blocked(title, klass):
    got, marker = eg.classify(title)
    assert got == klass, f"{title!r} -> {got} (marker {marker!r}), expected {klass}"
    assert not eg.is_eligible(title)
    assert eg.skip_note(title) == f"ineligible: grad {eg.GRAD_YEAR}, role is {klass}"


@pytest.mark.parametrize("title", ELIGIBLE_TITLES)
def test_intern_and_coop_pass(title):
    klass, _ = eg.classify(title)
    assert klass == eg.INTERN_COOP, f"{title!r} -> {klass}"
    assert eg.is_eligible(title)
    assert eg.skip_note(title) == ""


def test_intern_marker_beats_every_ineligible_marker():
    # Some employers post the same req twice with only the suffix differing.
    assert eg.classify("Campus Software Engineer (Intern)")[0] == eg.INTERN_COOP
    assert eg.classify("Campus Software Engineer (Full-Time)")[0] == eg.FULL_TIME
    assert eg.classify("Campus Quantitative Researcher, UG/MS (Intern)")[0] == eg.INTERN_COOP
    assert eg.classify("Campus Quantitative Researcher, UG/MS (Full-Time)")[0] == eg.FULL_TIME
    # a full-time-hours internship is still an internship
    assert eg.classify("Software Engineer Intern (Full-Time)")[0] == eg.INTERN_COOP
    # and "campus" alone must never mean new-grad, or the intern rows above get purged
    assert eg.classify("Campus AI Research Engineer - Deep Learning (Intern)")[0] == eg.INTERN_COOP


def test_season_year_does_not_rescue_a_graduation_window():
    # A season+year in a "Graduation Date:" clause is a GRADUATION window, not an intern term.
    t = "Software Engineer I, Entry-Level (Graduation Date: Fall 2025-Summer 2026)"
    klass, _ = eg.classify(t)
    assert klass == eg.FULL_TIME
    assert not eg.is_eligible(t)


def test_new_grad_beats_full_time_level_marker():
    # both markers present; the new-grad reason is the more specific one
    assert eg.classify("Associate Software Engineer - New Grad Card Expansion")[0] == eg.NEW_GRAD


def test_unclear_passes_the_gate():
    # no class signal -> never silently dropped, stays for human review
    for t in ["Technical Sourcer", "Data Annotation Specialist", "Trust & Safety Operations"]:
        assert eg.classify(t)[0] == eg.UNCLEAR
        assert eg.is_eligible(t)
        assert eg.skip_note(t) == ""


def test_coop_with_no_intern_word_in_the_title_survives():
    # A term-length co-op title never says "intern"/"co-op" explicitly, only a season + month
    # count. The bare-noun catch-all would call it FULL_TIME and purge it, so the term signal
    # must run first.
    t = "2026 Fall Developer - Risk Management (4 mo)"
    assert eg.classify(t)[0] == eg.INTERN_COOP
    assert eg.is_eligible(t)
    # season and year appear in both orders across sources
    assert eg.classify("Data Engineer Intern - Ads Data - 2026 Summer")[0] == eg.INTERN_COOP
    assert eg.classify("Software Engineer, Platform (Fall 2026)")[0] == eg.INTERN_COOP


def test_graduate_program_is_new_grad_not_unclear():
    # Regression: an earlier pattern wrote "programme?" (double m + optional e), so "Graduate
    # Program" never matched and grad-program postings leaked through as UNCLEAR.
    for t in ["2026 Graduate Program - Cyber Security",
              "2026 Graduate Program - Data Analytics & AI",
              "Quantitative Trader - 2027 Graduate Program (August Start)"]:
        assert eg.classify(t)[0] == eg.NEW_GRAD, t
        assert not eg.is_eligible(t)


def test_bare_role_nouns_are_full_time():
    for t in ["Developer", "Developer Experience Engineer", "Software Development Engineer - 2026",
              "Core Engine Developer - Systems (C++)", "Quantitative UX Researcher"]:
        assert eg.classify(t)[0] == eg.FULL_TIME, t


def test_level_suffix_does_not_eat_real_words():
    # "I" as a level, not as the first letter of the next word
    assert eg.classify("Software Engineer, Infrastructure")[1] != "i"
    assert eg.classify("Software Engineer, Identity")[0] == eg.FULL_TIME  # career noun, not level I
    assert eg.classify("Machine Learning Engineer, Inference")[0] == eg.FULL_TIME
    # the real level suffix still fires
    assert eg.classify("Data Analyst III")[0] == eg.FULL_TIME


def test_jd_graduation_window_blocks_only_when_every_year_is_past():
    # a JD window that excludes GRAD_YEAR marks NEW_GRAD on an otherwise-unclear title
    past = eg.GRAD_YEAR - 2
    future = eg.GRAD_YEAR + 1
    assert eg.classify("Technical Sourcer", jd=f"You must graduate by Spring {past}.")[0] == eg.NEW_GRAD
    # an open window, or one that includes the applicant, must NOT be blocked
    assert eg.classify("Technical Sourcer", jd=f"Graduating in {future} or later.")[0] == eg.UNCLEAR
    assert eg.classify("Technical Sourcer", jd="No graduation date requirement.")[0] == eg.UNCLEAR
    # the JD never overrides a student lane in the title
    assert eg.classify("Software Engineer Intern", jd=f"Class of {past} only")[0] == eg.INTERN_COOP


def test_filter_rows_drops_ineligible_and_keeps_the_rest():
    rows = [{"title": "Software Engineer Intern"}, {"title": "Software Engineer, New Grad"},
            {"title": "Data Scientist"}, {"title": "Technical Sourcer"}]
    kept = eg.filter_rows(rows, log=False)
    assert [r["title"] for r in kept] == ["Software Engineer Intern", "Technical Sourcer"]


def test_intern_markers_do_not_match_inside_other_words():
    """Load-bearing word boundaries. "Internal", "International" and "Cooperative" contain the
    substrings intern/co-op. A substring match would mark these full-time reqs INTERN_COOP and
    leave them in the queue, which is the leak wearing a disguise."""
    for t in ["Software Engineer, Internal Systems",
              "Internal Product Engineer, Developer Productivity AI",
              "Software Engineer, Backend (Cooperative AI)",
              "Business Strategy Developer - International",
              "Full Stack Engineer - Internal Audit",
              "Software Developer - Internal Compute Frameworks (Rust)"]:
        klass, marker = eg.classify(t)
        assert klass == eg.FULL_TIME, f"{t!r} -> {klass} via {marker!r}"
    # and the real words still match
    assert eg.classify("Software Engineer Intern")[0] == eg.INTERN_COOP
    assert eg.classify("Data Engineer Co-op")[0] == eg.INTERN_COOP


def test_repair_split_notes_is_lossless():
    # A notes cell written unquoted, so its own comma made an extra field.
    fields = ["id", "title", "notes"]
    rows = [{"id": "511", "title": "Data Analyst", "notes": "rejected, found in reconcile 2026-07-16",
             None: [" tracker was stale"]},
            {"id": "512", "title": "SWE Intern", "notes": "fine"}]
    n = eg._repair_split_notes(rows, fields)
    assert n == 1
    assert rows[0]["notes"] == "rejected, found in reconcile 2026-07-16, tracker was stale"
    assert None not in rows[0]
    assert rows[1]["notes"] == "fine"  # untouched


def test_tracker_is_well_formed():
    # every row has exactly the header's field count, so no cell is split across columns
    import csv as _csv
    path = ROOT / "data" / "tracker.csv"
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(_csv.reader(f))
    width = len(rows[0])
    bad = [i for i, r in enumerate(rows, 1) if len(r) != width]
    assert not bad, f"tracker.csv rows with wrong field count: {bad[:5]} (header={width})"


def test_grad_year_matches_the_applicant_profile():
    prof = (ROOT / "data" / "applicant_profile.yaml").read_text(encoding="utf-8")
    assert f'graduation_date_iso: "{eg.GRAD_YEAR}-04-30"' in prof
