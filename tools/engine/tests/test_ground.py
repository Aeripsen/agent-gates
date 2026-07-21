"""Tests for the grounding gate: the substring post-condition, the grounded/rejected split, and
the tolerant claim parsing that free models force on us (fenced JSON, object-shaped replies, a
single unwrapped claim, an array buried in prose).

These exercise the pure, offline parts of ground.py. `extract_grounded` is not tested here: it
calls the live free-model router (llm_router.chat) and needs network + keys. Everything that makes
the gate a gate (quote_found / gate / _coerce_claims / _parse_claims) is deterministic and covered.

Note what these tests deliberately do NOT assert: that a grounded quote SUPPORTS its claim. The
gate only proves the quote is verbatim in the source; a real quote paired with a false claim is
grounded here on purpose. See ground.py's "what this gate cannot catch" note. This is the same
"real term in a false context" blind spot honesty_gate.py documents.
"""
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
