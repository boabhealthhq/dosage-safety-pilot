"""
Ibuprofen test suite. Same stdlib-only, no-pytest pattern as paracetamol's -
run with: python3 tests/test_ibuprofen.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dosage_safety import check_order, PatientInfo, Status  # noqa: E402

CASES = [
    # ---- normal / should PASS ----
    ("standard peds mg/kg within range (8mg/kg), PRN range interval",
     "ibuprofen 8mg/kg PO 6-8 hourly PRN",
     PatientInfo(age_years=5, weight_kg=20), Status.PASS),

    ("standard peds at low end of range (5mg/kg)",
     "ibuprofen 5mg/kg PO 6-8 hourly PRN",
     PatientInfo(age_years=4, weight_kg=16), Status.PASS),

    ("standard peds at top of range exactly (10mg/kg)",
     "ibuprofen 10mg/kg PO 6-8 hourly PRN",
     PatientInfo(age_years=5, weight_kg=20), Status.PASS),

    ("brand name alias resolves correctly (nurofen)",
     "nurofen 5mg/kg PO 6-8 hourly PRN",
     PatientInfo(age_years=4, weight_kg=16), Status.PASS),

    ("peds fixed mg dose within weight-based range",
     "ibuprofen 160mg PO 6-8 hourly PRN",
     PatientInfo(age_years=6, weight_kg=20), Status.PASS),

    ("adult standard 200mg 6hourly - 800mg/day, under OTC ceiling",
     "ibuprofen 200mg PO 6 hourly",
     PatientInfo(age_years=35, weight_kg=75), Status.PASS),

    ("adult 400mg TDS - exactly at 1200mg/day OTC ceiling, not over",
     "ibuprofen 400mg PO TDS",
     PatientInfo(age_years=40, weight_kg=80), Status.PASS),

    ("drug mentioned with no dose stated",
     "continue ibuprofen as charted, otherwise stable",
     PatientInfo(age_years=5, weight_kg=20), Status.PASS),

    # ---- dangerous / should FLAG or BLOCK ----
    ("peds single dose exceeds 400mg hard cap",
     "ibuprofen 500mg PO 6 hourly",
     PatientInfo(age_years=12, weight_kg=45), Status.BLOCK),

    ("peds dosing interval below 6hr minimum",
     "ibuprofen 8mg/kg PO 4 hourly",
     PatientInfo(age_years=8, weight_kg=25), Status.BLOCK),

    ("peds daily total exceeds effective per-kg ceiling (lower than absolute)",
     "ibuprofen 380mg PO 6 hourly",
     PatientInfo(age_years=13, weight_kg=35), Status.BLOCK),

    ("under 3 months - avoid without clinician review",
     "ibuprofen 5mg/kg PO 8 hourly PRN",
     PatientInfo(age_years=0.1, weight_kg=5), Status.FLAG),

    ("mg/kg rate above standard range, PRN interval so daily-total not computed",
     "ibuprofen 15mg/kg PO 6-8 hourly PRN",
     PatientInfo(age_years=5, weight_kg=20), Status.FLAG),

    ("adult single dose over 400mg, no frequency stated",
     "ibuprofen 600mg PO",
     PatientInfo(age_years=35, weight_kg=75), Status.FLAG),

    ("adult daily total exceeds OTC ceiling but not prescription ceiling",
     "ibuprofen 400mg PO 6 hourly",
     PatientInfo(age_years=35, weight_kg=75), Status.FLAG),

    ("adult daily total exceeds even prescription-strength ceiling",
     "ibuprofen 800mg PO 4 hourly",
     PatientInfo(age_years=35, weight_kg=75), Status.BLOCK),

    ("misspelled drug name, genuinely dangerous dose - must not go silent",
     "ibuprofn 500mg PO 6 hourly",
     PatientInfo(age_years=12, weight_kg=45), Status.BLOCK),

    # ---- missing-input handling ----
    ("patient age not provided",
     "ibuprofen 5mg/kg PO 6-8 hourly PRN",
     PatientInfo(weight_kg=20), Status.FLAG),

    ("patient weight not provided for a child",
     "ibuprofen 5mg/kg PO 6-8 hourly PRN",
     PatientInfo(age_years=5), Status.FLAG),
]


def run():
    passed = 0
    failed = 0
    for label, text, patient, expected in CASES:
        decisions = check_order(text, patient)
        if not decisions:
            print(f"FAIL  [{label}] - no decision produced at all")
            failed += 1
            continue
        actual = decisions[0].status
        if actual == expected:
            print(f"pass  [{label}] -> {actual.value}")
            passed += 1
        else:
            print(f"FAIL  [{label}] -> got {actual.value}, expected {expected.value}")
            print(f"        reasons: {decisions[0].reasons}")
            failed += 1

    print(f"\n{passed} passed, {failed} failed, {len(CASES)} total")
    return failed == 0


if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
