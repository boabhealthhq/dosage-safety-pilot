"""
Amoxicillin test suite. Same stdlib-only, no-pytest pattern as the others -
run with: python3 tests/test_amoxicillin.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dosage_safety import PatientInfo, Status, check_order  # noqa: E402

CASES = [
    # ---- normal / should PASS - deliberately wide, spanning standard through high-dose ----
    ("standard low-end peds (25mg/kg TDS = 75mg/kg/day)",
     "amoxicillin 25mg/kg PO TDS",
     PatientInfo(age_years=5, weight_kg=20), Status.PASS),

    ("high-dose peds within legitimate range (40mg/kg BD = 80mg/kg/day)",
     "amoxicillin 40mg/kg PO BD",
     PatientInfo(age_years=5, weight_kg=20), Status.PASS),

    ("high-dose peds right at the ceiling (45mg/kg BD = 90mg/kg/day, not over)",
     "amoxicillin 45mg/kg PO BD",
     PatientInfo(age_years=5, weight_kg=20), Status.PASS),

    ("AU spelling variant (amoxycillin)",
     "amoxycillin 500mg PO TDS",
     PatientInfo(age_years=30, weight_kg=70), Status.PASS),

    ("adult standard 500mg TDS",
     "amoxicillin 500mg PO TDS",
     PatientInfo(age_years=40, weight_kg=75), Status.PASS),

    ("adult higher standard dose 1g BD - within range, under absolute cap",
     "amoxicillin 1000mg PO BD",
     PatientInfo(age_years=40, weight_kg=75), Status.PASS),

    ("infant under 3mo standard reduced dosing (10mg/kg BD = 20mg/kg/day)",
     "amoxicillin 10mg/kg PO BD",
     PatientInfo(age_years=0.1, weight_kg=5), Status.PASS),

    ("drug mentioned with no dose stated",
     "continue amoxicillin as charted, otherwise stable",
     PatientInfo(age_years=5, weight_kg=20), Status.PASS),

    # ---- dangerous / should FLAG or BLOCK ----
    ("peds single dose exceeds 2g absolute cap",
     "amoxicillin 2500mg PO TDS",
     PatientInfo(age_years=12, weight_kg=50), Status.BLOCK),

    ("peds daily total blows past both per-dose and absolute daily cap",
     "amoxicillin 40mg/kg PO TDS",
     PatientInfo(age_years=15, weight_kg=60), Status.BLOCK),

    ("peds dose double the intended high-dose regimen (90mg/kg per dose, not per day)",
     "amoxicillin 90mg/kg PO BD",
     PatientInfo(age_years=5, weight_kg=20), Status.BLOCK),

    ("peds interval below 8hr minimum",
     "amoxicillin 25mg/kg PO 4 hourly",
     PatientInfo(age_years=5, weight_kg=20), Status.BLOCK),

    ("peds daily total modestly above high-dose ceiling - FLAG not BLOCK",
     "amoxicillin 50mg/kg PO BD",
     PatientInfo(age_years=5, weight_kg=20), Status.FLAG),

    ("infant under 3mo dose exceeds reduced ceiling",
     "amoxicillin 20mg/kg PO BD",
     PatientInfo(age_years=0.1, weight_kg=5), Status.BLOCK),

    ("infant under 3mo interval below 12hr minimum",
     "amoxicillin 10mg/kg PO 8 hourly",
     PatientInfo(age_years=0.1, weight_kg=5), Status.BLOCK),

    ("adult exceeds 4g/day absolute ceiling",
     "amoxicillin 1500mg PO TDS",
     PatientInfo(age_years=40, weight_kg=75), Status.BLOCK),

    ("adult interval below 8hr minimum",
     "amoxicillin 500mg PO 4 hourly",
     PatientInfo(age_years=40, weight_kg=75), Status.BLOCK),

    ("misspelled drug name, genuinely dangerous dose - must not go silent",
     "amoxicilin 2500mg PO TDS",
     PatientInfo(age_years=12, weight_kg=50), Status.BLOCK),

    # ---- missing-input handling ----
    ("patient age not provided",
     "amoxicillin 500mg PO TDS",
     PatientInfo(weight_kg=70), Status.FLAG),

    ("patient weight not provided for a child",
     "amoxicillin 25mg/kg PO TDS",
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
