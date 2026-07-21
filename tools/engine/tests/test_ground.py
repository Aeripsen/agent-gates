"""Tests for the grounding gate: the substring post-condition, the grounded/rejected split, and
the tolerant claim parsing that free models force on us (fenced JSON, object-shaped replies, a
single unwrapped claim, an array buried in prose).

These exercise the pure, offline parts of ground.py. `extract_grounded` is not tested here: it
calls the live free-model router (llm_router.chat) and needs network + keys. Everything that makes
the gate a gate (quote_found / gate / _coerce_claims / _parse_claims) is deterministic and covered.

The gate also checks, lexically, that the quote's words match the claim's words. The tests for
that are at the bottom, and they include the cases it still gets wrong: a real quote carrying an
invented extra clause, a negation flip, and a claim that would need reasoning over the quote
rather than word matching. Those are asserted at their current (wrong) behaviour on purpose, so
a change in them shows up as a failing test instead of going unnoticed.
"""
import json
from pathlib import Path

import pytest

import ground


# --- quote_found: whitespace-normalized, case-insensitive substring ------------------------------

def test_quote_found_exact():
    assert ground.quote_found("Charger A2", "Norco Charger A2 alloy, $899")


def test_quote_found_normalizes_whitespace_and_case():
    # ragged whitespace and different case in the quote still match the source
    assert ground.quote_found("charger   a2\n alloy", "Norco Charger A2 alloy")


def test_quote_found_absent_quote_fails():
    assert not ground.quote_found("carbon frame", "Norco Charger A2 alloy")


def test_quote_found_empty_quote_fails():
    assert not ground.quote_found("", "anything at all")
    assert not ground.quote_found("   ", "anything at all")


# --- gate: split claims into grounded / rejected -------------------------------------------------

def test_gate_splits_on_quote_presence():
    source = "The K2 Maysis boot is US 11 and ships free."
    claims = [
        {"claim": "boot is size US 11", "verbatim_quote": "US 11"},
        {"claim": "boot is waterproof", "verbatim_quote": "fully waterproof"},
    ]
    grounded, rejected = ground.gate(claims, source)
    assert grounded == [{"claim": "boot is size US 11", "verbatim_quote": "US 11"}]
    assert rejected == [{"claim": "boot is waterproof", "verbatim_quote": "fully waterproof"}]


def test_gate_rejects_missing_quote_key():
    grounded, rejected = ground.gate([{"claim": "no quote provided"}], "some source text")
    assert grounded == []
    assert len(rejected) == 1


def test_gate_rejects_non_dict_items():
    grounded, rejected = ground.gate(["not a dict", 42, None], "some source text")
    assert grounded == []
    assert rejected == ["not a dict", 42, None]


def test_gate_passes_extra_keys_through():
    source = "the price is $899 today"
    claims = [
        {"claim": "the price is $899", "verbatim_quote": "price is $899", "confidence": 0.9, "url": "x"}
    ]
    grounded, _ = ground.gate(claims, source)
    assert grounded[0]["confidence"] == 0.9
    assert grounded[0]["url"] == "x"


# --- _coerce_claims: accept the shapes free models actually return -------------------------------

def test_coerce_bare_list():
    assert ground._coerce_claims([{"claim": "a"}, {"claim": "b"}]) == [{"claim": "a"}, {"claim": "b"}]


def test_coerce_bare_list_drops_non_dicts():
    assert ground._coerce_claims([{"claim": "a"}, "junk", 3]) == [{"claim": "a"}]


@pytest.mark.parametrize("key", ["claims", "facts", "results", "items", "data"])
def test_coerce_wrapper_object(key):
    obj = {key: [{"claim": "a"}]}
    assert ground._coerce_claims(obj) == [{"claim": "a"}]


def test_coerce_single_unwrapped_claim():
    obj = {"claim": "one thing", "verbatim_quote": "one thing"}
    assert ground._coerce_claims(obj) == [obj]


def test_coerce_empty_object_is_zero_claims_not_failure():
    assert ground._coerce_claims({}) == []
    assert ground._coerce_claims({"error": "nothing relevant found"}) == []


def test_coerce_non_container_is_none():
    assert ground._coerce_claims("a string") is None
    assert ground._coerce_claims(42) is None


# --- _parse_claims: tolerant of fences and object-shaped replies ---------------------------------

def test_parse_plain_array():
    assert ground._parse_claims('[{"claim": "a", "verbatim_quote": "a"}]') == [
        {"claim": "a", "verbatim_quote": "a"}
    ]


def test_parse_fenced_json():
    raw = '```json\n[{"claim": "a", "verbatim_quote": "a"}]\n```'
    assert ground._parse_claims(raw) == [{"claim": "a", "verbatim_quote": "a"}]


def test_parse_object_wrapped_array():
    raw = '{"claims": [{"claim": "a", "verbatim_quote": "a"}]}'
    assert ground._parse_claims(raw) == [{"claim": "a", "verbatim_quote": "a"}]


def test_parse_single_object():
    raw = '{"claim": "a", "verbatim_quote": "a"}'
    assert ground._parse_claims(raw) == [{"claim": "a", "verbatim_quote": "a"}]


def test_parse_array_embedded_in_prose():
    raw = 'Here are the claims:\n[{"claim": "a", "verbatim_quote": "a"}]\nHope that helps.'
    assert ground._parse_claims(raw) == [{"claim": "a", "verbatim_quote": "a"}]


def test_parse_empty_object_is_no_claims():
    assert ground._parse_claims("{}") == []


def test_parse_no_json_raises():
    with pytest.raises(ValueError):
        ground._parse_claims("sorry, I could not find anything")


# --- claim_supported: the quote has to match the claim, not just exist -------------------------

def test_support_paraphrase_of_a_fragment_quote():
    assert ground.claim_supported("The Norco Charger A2 is on sale for $899.", "on sale for $899")


def test_support_one_detail_pulled_out_of_a_long_quote():
    quote = "Ships free in Canada, returns within 30 days, boot size US 11"
    assert ground.claim_supported("The boot is size US 11.", quote)


def test_support_rejects_a_swapped_number():
    assert not ground.claim_supported("The bike is on sale for $699.", "on sale for $899")
    assert not ground.claim_supported("The library requires Node 22.", "requires Node 20 or newer")


def test_support_rejects_an_unrelated_quote():
    assert not ground.claim_supported("The bike has a carbon frame.", "on sale for $899")


def test_support_rejects_a_single_shared_word():
    # "closure" alone does not tie the claim to the quote, and the claim contradicts it
    assert not ground.claim_supported(
        "The boot has a traditional lace closure.", "uses a Boa closure"
    )


def test_support_rejects_empty_sides():
    assert not ground.claim_supported("", "on sale for $899")
    assert not ground.claim_supported("The bike is on sale.", "")


def test_support_score_bounds():
    assert ground.support_score("on sale for $899", "on sale for $899") == 1.0
    assert ground.support_score("carbon frame", "on sale for $899") == 0.0


def test_support_threshold_is_overridable():
    claim, quote = "The internship is for Summer 2027.", "Intern for Summer 2027"
    assert ground.claim_supported(claim, quote, threshold=0.5)
    assert not ground.claim_supported(claim, quote, threshold=0.9)


# --- gate: the adversarial case the old gate could not see -------------------------------------

def test_gate_rejects_a_real_verbatim_quote_on_an_unrelated_claim():
    source = "Norco Charger A2 alloy hardtail, on sale for $899. Free shipping in Canada."
    claim = {"claim": "The bike has a carbon frame.", "verbatim_quote": "on sale for $899"}
    assert ground.quote_found(claim["verbatim_quote"], source)  # the quote is genuinely there
    grounded, rejected = ground.gate([claim], source)
    assert grounded == []
    assert rejected == [claim]


def test_gate_rejects_a_price_edited_in_the_claim():
    source = "Norco Charger A2 alloy hardtail, on sale for $899."
    claim = {"claim": "The Norco Charger A2 is on sale for $699.", "verbatim_quote": "on sale for $899"}
    grounded, _ = ground.gate([claim], source)
    assert grounded == []


def test_gate_threshold_is_overridable():
    source = "We are hiring a Software Engineering Intern for Summer 2027 in Toronto."
    claims = [{"claim": "The internship is for Summer 2027.", "verbatim_quote": "Intern for Summer 2027"}]
    assert ground.gate(claims, source, threshold=0.5)[0] == claims
    assert ground.gate(claims, source)[0] == []  # default 0.7 is stricter than this paraphrase


# --- what the support check still lets through, asserted so it cannot drift quietly ------------

def test_known_gap_quote_plus_an_invented_clause_still_passes():
    source = "Returns accepted within 30 days of delivery."
    claim = {
        "claim": "Returns are accepted within 30 days and return shipping is refunded.",
        "verbatim_quote": "Returns accepted within 30 days",
    }
    assert ground.gate([claim], source)[0] == [claim]


def test_known_gap_negation_flip_still_passes():
    source = "Python 3.13 removed the deprecated `imp` module."
    claim = {
        "claim": "The imp module was deprecated in Python 3.13 but not removed.",
        "verbatim_quote": "Python 3.13 removed the deprecated `imp` module",
    }
    assert ground.gate([claim], source)[0] == [claim]


def test_known_cost_a_number_inside_a_quoted_range_is_dropped():
    source = "The K2 Maysis boot ships in US sizes 7 through 13."
    claim = {"claim": "The boot is available in US size 11.", "verbatim_quote": "ships in US sizes 7 through 13"}
    assert ground.gate([claim], source)[0] == []


# --- the labelled eval set, locked to the numbers written into RESULTS.md ----------------------

_CASES = json.loads(
    (Path(__file__).resolve().parents[1] / "eval" / "relevance_cases.json").read_text(
        encoding="utf-8"
    )
)["cases"]


def _keep(case):
    claim = {"claim": case["claim"], "verbatim_quote": case["quote"]}
    return bool(ground.gate([claim], case["source"])[0])


def test_eval_set_quotes_are_all_verbatim():
    # the whole point of the set: presence alone cannot separate these
    assert all(ground.quote_found(c["quote"], c["source"]) for c in _CASES)


def test_eval_set_scores_match_the_committed_results():
    kept_supported = sum(1 for c in _CASES if c["label"] == "supported" and _keep(c))
    kept_misattributed = sum(1 for c in _CASES if c["label"] == "misattributed" and _keep(c))
    assert (kept_supported, kept_misattributed) == (16, 2)
