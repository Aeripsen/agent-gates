# Job-search gates

Two small, independent gates extracted from a larger personal job-application pipeline. Both are
plain Python, stdlib only, and both exist because a production run of that pipeline actually
failed in the way each gate now prevents.

## `src/eligibility_gate.py` - don't queue a role you cannot be hired into

Classifies a job title into `INTERN_COOP` / `NEW_GRAD` / `FULL_TIME` / `UNCLEAR`, so a student
applicant is never queued for (or auto-applied to) a role class they structurally cannot hold.
The classification is title-only (cheap, high precision, no HTTP) with a JD-based backstop for an
explicit graduation-window clause.

This exists because an audit of a real submission log found that upstream scoring code was giving
NEW_GRAD and FULL_TIME titles a *bonus*, i.e. ranking the exact role classes that auto-reject a
student applicant as the applicant's best matches. `eligibility_gate.is_eligible()` is now the
single source of truth every sourcing/queueing/apply path is expected to check.

## `src/honesty_gate.py` - don't let a generated resume vouch for itself

Scans generated resume text (summary, bullets, cover letter) for three fabrication patterns: a
tool/framework/domain named in the generation but absent from the applicant's real evidence, an
"N years of experience" claim the applicant's real role dates cannot support, and generic filler
openings. The interesting design point is the evidence/claims split: the resume's own Skills line
is never used to validate the resume, because that would let the resume prove itself. See the
module docstring, especially the section titled "WHAT THIS GATE CANNOT CATCH" - a keyword filter
has real, structural blind spots, and the honest thing to do is document them rather than
overclaim what a "pass" means.

## Data in this repo

Everything under `data/` is synthetic example content for a fictional applicant ("Jane Example"),
written specifically so the tests in `tests/` can run standalone without any real resume, real
job-application history, or real personal data. Replace it with your own resume/evidence files if
you want to use either gate for yourself; both gates read from generic relative paths, not
anything specific to the fictional example.

## Running the tests

```
pip install pytest
python -m pytest projects/job-search/tests -q
```
