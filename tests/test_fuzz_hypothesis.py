"""
Property-based fuzz test using hypothesis. Could NOT be run in the build
environment (no network access to pip install hypothesis there) - this is
written for you to run locally:

    pip install hypothesis
    python -m pytest tests/test_fuzz_hypothesis.py -v
    (or: python tests/test_fuzz_hypothesis.py)

The hand-rolled equivalent (test_fuzz_manual.py) already ran 3000 randomized
cases with zero crashes, plus a separate adversarial pass checking for
catastrophic regex backtracking (also clean). This file goes further:
hypothesis doesn't just generate random input, it automatically SHRINKS any
failing case down to the smallest input that still reproduces the failure -
much faster to debug than a 200-character random string that happened to
crash something.

The property being tested throughout: check_order() must NEVER raise an
exception, and must always return either an empty list or a list of
well-formed Decision objects - regardless of how malformed the input is.
This is the property that actually matters for a safety tool: garbage in
should mean "nothing meaningful found" or "flagged as unverifiable," never
"the process falls over."
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dosage_safety import check_order, PatientInfo, Decision, Status  # noqa: E402

try:
    from hypothesis import given, strategies as st, settings, HealthCheck
except ImportError:
    print("hypothesis not installed - run: pip install hypothesis")
    sys.exit(1)


# ------------------------------------------------------------------
# Property 1: arbitrary text + arbitrary (possibly implausible) patient
# data must never crash check_order(), regardless of content.
# ------------------------------------------------------------------

@given(
    text=st.text(min_size=0, max_size=500),
    age=st.one_of(st.none(), st.floats(allow_nan=False, allow_infinity=False)),
    weight=st.one_of(st.none(), st.floats(allow_nan=False, allow_infinity=False)),
)
@settings(max_examples=2000, suppress_health_check=[HealthCheck.too_slow])
def test_never_crashes_on_arbitrary_input(text, age, weight):
    patient = PatientInfo(age_years=age, weight_kg=weight)
    result = check_order(text, patient)
    assert isinstance(result, list)
    for decision in result:
        assert isinstance(decision, Decision)
        assert isinstance(decision.status, Status)
        assert isinstance(decision.reasons, list)


# ------------------------------------------------------------------
# Property 2: text built specifically from realistic vocabulary
# (drug names, dose units, interval words) in random order/combination -
# more likely to hit real extraction edge cases than pure noise.
# ------------------------------------------------------------------

CLINICAL_WORDS = st.sampled_from([
    "paracetamol", "ibuprofen", "amoxicillin", "panadol", "nurofen",
    "amoxil", "pcm", "ibu", "mg", "kg", "g", "mcg", "PO", "IV", "IM",
    "hourly", "daily", "divided", "TDS", "BD", "QID", "PRN", "stat",
    "every", "four", "six", "eight", "twelve", "twenty-four", "per",
    "kilo", "gram", "times", "a", "day", "the", "for", "give", "of",
    ".", ",", "-", "/", "\n", "  ",
])

@given(words=st.lists(CLINICAL_WORDS, min_size=0, max_size=40))
@settings(max_examples=2000, suppress_health_check=[HealthCheck.too_slow])
def test_never_crashes_on_clinical_vocabulary_soup(words):
    text = " ".join(words)
    patient = PatientInfo(age_years=30, weight_kg=70)
    result = check_order(text, patient)
    assert isinstance(result, list)


# ------------------------------------------------------------------
# Property 3: mutated versions of known-good orders must never crash,
# even if the mutation makes the dose/interval unparseable.
# ------------------------------------------------------------------

KNOWN_GOOD_ORDERS = [
    "paracetamol 15mg/kg PO 4-6 hourly PRN",
    "ibuprofen 200mg PO QID",
    "amoxicillin 40mg/kg divided q8h",
    "Panadol 1g PO stat",
]

@given(
    base=st.sampled_from(KNOWN_GOOD_ORDERS),
    mutation_positions=st.lists(st.integers(min_value=0, max_value=200), max_size=10),
    replacement_chars=st.text(min_size=0, max_size=10),
)
@settings(max_examples=1000, suppress_health_check=[HealthCheck.too_slow])
def test_never_crashes_on_mutated_known_good_orders(base, mutation_positions, replacement_chars):
    chars = list(base)
    for pos in mutation_positions:
        if chars and pos < len(chars):
            chars[pos % len(chars)] = replacement_chars[0] if replacement_chars else "?"
    text = "".join(chars)
    patient = PatientInfo(age_years=30, weight_kg=70)
    result = check_order(text, patient)
    assert isinstance(result, list)


if __name__ == "__main__":
    print("Running hypothesis property tests...")
    test_never_crashes_on_arbitrary_input()
    print("  test_never_crashes_on_arbitrary_input: PASS")
    test_never_crashes_on_clinical_vocabulary_soup()
    print("  test_never_crashes_on_clinical_vocabulary_soup: PASS")
    test_never_crashes_on_mutated_known_good_orders()
    print("  test_never_crashes_on_mutated_known_good_orders: PASS")
    print("\nAll property tests passed.")
