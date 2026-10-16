"""Pin the outcomes README.md quotes from examples/worked_examples.py, so the docs cannot drift."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import ground

_ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("worked_examples", _ROOT / "examples" / "worked_examples.py")
we = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(we)


def test_honesty_example_blocks_the_injected_stack_and_duration():
    reasons = [r for _, r in we.honesty_example()]
    assert "django" in reasons
    assert any(r.startswith("duration:'10 years of experience'") for r in reasons)


def test_eligibility_example_blocks_only_the_injected_senior_role():
    rows = {title: ok for title, ok, _ in we.eligibility_example()}
    assert rows == {
        "Software Engineering Intern, Summer 2027": True,
        "Senior Staff Engineer, Platform": False,
        "Research Assistant (Co-op)": True,
    }


def test_grounding_example_keeps_the_real_price_and_drops_the_injected_one():
    kept, dropped = we.grounding_example()
    assert [c["claim"] for c in kept] == ["The Trail Tent 2P costs $249"]
    assert [c["claim"] for c in dropped] == ["The Trail Tent 2P costs $0"]


def test_grounding_short_quote_without_the_model_name_is_a_false_reject():
    # documents the "2P" finding in the example's docstring; flip this test if ground.py fixes it
    assert not ground.claim_supported("The Trail Tent 2P costs $249", "Price: $249.")


def test_injection_example_flags_only_the_poisoned_record_with_all_three_markers():
    clean, flagged = we.injection_example()
    assert len(clean) == 2 and len(flagged) == 1
    kinds = {f.kind for f in flagged[0][1]}
    assert kinds == {"invisible", "override", "action_request"}


def test_script_runs_end_to_end(capsys):
    assert we.main() == 0
    out = capsys.readouterr().out
    assert out.count("BLOCKED") == 3 and "FLAGGED  S-01" in out
