"""The honesty gate, tested against the fabrication classes it was built to catch, plus one it
was built to admit it CANNOT catch.

The strings below are illustrative examples, not real generated content. The gate catches two of
the three classes below by design. The third is documented as uncatchable rather than faked, and
test_the_uncatchable_class_is_still_uncatchable pins that honesty down: if someone later claims
coverage it does not have, that test is where the claim gets checked.
"""
from pathlib import Path

import pytest

import honesty_gate as hg

ROOT = Path(__file__).resolve().parents[1]


def _obj(summary="", bullets=None, cover=""):
    return {"summary": summary, "tailored_bullets": bullets or [], "cover_letter": cover}


# ---- the cover letter must be scanned, not just the summary/bullets ---------------------------

def test_cover_letter_is_scanned():
    """The gate must build its checked fields from summary + tailored_bullets + cover_letter. A
    gate that skips the cover letter reports "pass" while a fabrication reaches the reader through
    the one field nobody is watching."""
    v = hg.check(_obj(cover="I built our Salesforce Apex and Visualforce integrations."))
    assert v, "cover letter is not being scanned"
    assert {t for _f, t in v} >= {"salesforce", "apex", "visualforce"}
    assert all(f == "cover_letter" for f, _t in v)


def test_all_three_fields_are_covered():
    assert set(hg._fields_of(_obj("s", ["b"], "c"))) == {"summary", "bullet0", "cover_letter"}


# ---- fabrication class 1: an authorship claim the evidence does not support --------------------

def test_llm_authorship_fabrication_is_caught():
    """The synthetic evidence corpus documents ML work as a classifier project (built with,
    not built-from-scratch); "llm" itself is evidence-present (the applicant orchestrates LLMs
    via a router), so only the build/train verbs, which are evidence-absent, should fire."""
    v = hg.check(_obj(cover="I have spent two years building and training large language models."))
    assert ("cover_letter", "large language model") in v


def test_real_llm_orchestration_work_still_passes():
    """The distinction that makes the check above safe: genuinely orchestrating/routing LLMs is
    not the same claim as building or training one, and must not be flagged."""
    assert hg.check(_obj(bullets=["Built Python automation with a free-LLM-router for drafting."])) == []
    assert hg._present("llm", hg.corpus_text()), "llm must stay evidence-present or the above lies"


# ---- fabrication class 2: an invented duration -------------------------------------------------

def test_duration_claim_exceeding_the_record_is_caught():
    v = hg.check(_obj(summary="Engineer with over 15 years of experience building pipelines."))
    assert len(v) == 1 and v[0][0] == "summary" and v[0][1].startswith("duration:")


def test_the_uncatchable_class_is_still_uncatchable():
    """"Over 8 months of experience" is NOT caught: the synthetic record's longest role alone
    covers more than that, so the claim sits inside the record and is not false on its face.
    Dates cannot decide it, and a check that guessed would reject honest drafts. The module
    docstring says so out loud. This test exists so that limit stays documented instead of
    quietly overclaimed."""
    assert hg.check(_obj(summary="Engineer with over 8 months of experience.")) == []
    assert max(hg.role_spans()) >= 8


def test_honest_disclaimer_is_not_flagged():
    """A real disclaimer pattern seen in drafted cover letters: "While I do not yet have 5+ years
    of experience ...". Flagging a candidate for admitting a gap would be the gate causing the
    dishonesty it exists to stop."""
    assert hg.check(_obj(cover="While I do not yet have 5+ years of experience, I am eager.")) == []


def test_duration_parsing():
    assert hg.duration_claims("over two years of experience") == [("over two years of experience", 24)]
    assert hg.duration_claims("with 1.5 years of experience designing APIs")[0][1] == 18
    assert hg.duration_claims("5+ years of experience")[0][1] == 60
    assert hg.duration_claims("over 8 months of experience")[0][1] == 8
    assert hg.duration_claims("no duration here") == []


def test_role_spans_parse_the_experience_file():
    """The parser must find every role the printed resume shows, and the ceiling must track it.

    Counts are not pinned to a number: experience.tex legitimately changes when a role is added
    or cut for space. Pinning an exact count would make a normal edit look like a regression.
    What must hold is that parsing works and the ceiling reflects what is on the page, since a
    duration claim is only defensible against the resume the reader is holding.
    """
    spans = hg.role_spans()
    assert len(spans) >= 3, f"expected to parse the roles in experience.tex, got {spans}"
    assert all(s > 0 for s in spans), f"a role parsed to a non-positive span: {spans}"
    # The ceiling is earliest-start-to-today (calendar time), NOT the sum of role spans. The
    # synthetic roles overlap, so summing would let a claim double-count concurrent work.
    assert hg.total_span_months() >= max(spans), "ceiling must cover the longest single role"
    assert hg.total_span_months() <= sum(spans), "overlapping roles must not sum into the ceiling"


# ---- fabrication class 3: filler openings ------------------------------------------------------

def test_filler_opening_is_caught():
    v = hg.check(_obj(summary="Highly motivated and detail-oriented student eager to contribute."))
    assert v and v[0][1].startswith("filler:")


def test_filler_is_reported_once_not_per_overlapping_phrase():
    v = hg.check(_obj(cover="Highly motivated and detail-oriented student."))
    assert len(v) == 1, f"overlapping filler phrases double-reported: {v}"


# ---- the corpus split: evidence vs claims ------------------------------------------------------

def test_skills_tex_is_not_evidence():
    """The circularity this split prevents: skills.tex IS the resume's own Skills line, so
    grading generated claims against it would let the resume vouch for itself.

    This asserts the STRUCTURE (which file lands in which bucket), not which terms happen to be
    unevidenced today, since facts about the corpus belong in the corpus, not in asserts.
    """
    assert (hg._RESUME / "skills.tex") not in hg._EVIDENCE_FILES
    assert (hg._RESUME / "skills.tex") in hg._CLAIMS_FILES


def test_a_skills_line_term_alone_is_not_evidence():
    """Behaviour, on a synthetic corpus so it cannot drift with the real files: a term that appears
    ONLY in claims is reported as claims-only; the same term in evidence is not."""
    assert hg.claims_only_terms(claims="alpha beta", evidence="beta") == ["alpha"]
    assert hg.claims_only_terms(claims="alpha beta", evidence="alpha beta") == []


def test_build_to_true_is_evidence_so_a_vouched_skill_drops_off():
    """A dated, vouched-for skill in data/build-to-true.md IS evidence. Without that file the gate
    would have no home for a real skill that no shipped role documents, and absence of evidence is
    not evidence of absence."""
    bt = hg._JS / "data" / "build-to-true.md"
    assert bt in hg._EVIDENCE_FILES, "build-to-true.md must count as evidence"
    assert bt.exists(), "build-to-true.md is listed in the corpus but missing from disk"
    for t in ["react", "kubernetes", "terraform"]:
        assert t in hg.corpus_text(), f"{t} is vouched for in build-to-true.md; it must be evidence"
        assert t not in hg.claims_only_terms(), f"{t} is vouched for; stop reporting it as bare"


def test_evidence_backed_terms_never_trip_the_gate():
    assert hg.check(_obj(
        summary="Built a random-forest traffic classifier over a public flow dataset.",
        bullets=["Shipped a static HTML/CSS/JS site with a GitHub Actions CI/CD pipeline."],
        cover="I co-authored a peer-reviewed workshop paper on network intrusion detection.",
    )) == []


def test_gaps_field_may_name_anything():
    """"gaps" is where unmet requirements are supposed to be named; flagging it would punish
    honesty."""
    assert hg.check({"summary": "", "tailored_bullets": [], "cover_letter": "",
                     "gaps": ["No Salesforce or Laravel experience"]}) == []


def test_check_contract_is_stable_for_a_tailor_pipeline():
    """A caller pipeline is expected to do ", ".join(f"{f}:{t}" for f, t in viol) and reject on a
    truthy return, so the shape is load-bearing."""
    v = hg.check(_obj(cover="We used Laravel and Filament."), corpus=hg.corpus_text())
    assert isinstance(v, list) and all(isinstance(x, tuple) and len(x) == 2 for x in v)
    assert ", ".join(f"{f}:{t}" for f, t in v)
