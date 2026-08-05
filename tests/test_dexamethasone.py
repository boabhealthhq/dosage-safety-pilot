"""Dexamethasone test suite. python3 tests/test_dexamethasone.py"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dosage_safety import PatientInfo, Status, check_order  # noqa: E402

CASES = [
    ("standard low-end croup dose (0.15mg/kg)",
     "dexamethasone 0.15mg/kg PO stat", PatientInfo(age_years=3, weight_kg=15), Status.PASS),

    ("standard AAP high-end croup dose (0.6mg/kg)",
     "dex 0.6mg/kg PO stat", PatientInfo(age_years=3, weight_kg=15), Status.PASS),

    ("mid-range croup dose (0.3mg/kg)",
     "Decadron 0.3mg/kg PO stat", PatientInfo(age_years=5, weight_kg=20), Status.PASS),

    ("no dose stated",
     "continue dexamethasone as charted", PatientInfo(age_years=5, weight_kg=20), Status.PASS),

    ("large child at 0.6mg/kg genuinely exceeds the 16mg cap - correctly blocked, not silently reduced",
     "dexamethasone 0.6mg/kg PO stat", PatientInfo(age_years=12, weight_kg=40), Status.BLOCK),

    ("adult standard single dose",
     "dexamethasone 8mg PO stat", PatientInfo(age_years=40, weight_kg=75), Status.PASS),

    ("genuinely excessive - many multiples of standard",
     "dexamethasone 5mg/kg PO stat", PatientInfo(age_years=3, weight_kg=15), Status.BLOCK),

    ("modestly above standard rate, light enough patient that absolute cap isn't also triggered",
     "dexamethasone 1.2mg/kg PO stat", PatientInfo(age_years=1, weight_kg=10), Status.FLAG),

    ("adult dose above typical but not extreme - verify tier",
     "dexamethasone 30mg PO stat", PatientInfo(age_years=40, weight_kg=75), Status.FLAG),

    ("adult dose clearly excessive",
     "dexamethasone 60mg PO stat", PatientInfo(age_years=40, weight_kg=75), Status.BLOCK),

    ("interval too frequent for paediatric",
     "dexamethasone 0.3mg/kg PO 6 hourly", PatientInfo(age_years=5, weight_kg=20), Status.BLOCK),

    ("patient age not provided",
     "dexamethasone 8mg PO stat", PatientInfo(weight_kg=70), Status.FLAG),

    ("patient weight not provided for a child",
     "dexamethasone 0.3mg/kg PO stat", PatientInfo(age_years=5), Status.FLAG),

    ("IV route - NOT flagged, oral/IV/IM treated as clinically interchangeable for this drug",
     "dexamethasone 8mg IV stat", PatientInfo(age_years=30, weight_kg=70), Status.PASS),

    ("unusual SC route - flagged as unverified",
     "dexamethasone 8mg SC stat", PatientInfo(age_years=30, weight_kg=70), Status.FLAG),
]


def run():
    passed = failed = 0
    for label, text, patient, expected in CASES:
        d = check_order(text, patient)
        if not d:
            print(f"FAIL  [{label}] - no decision"); failed += 1; continue
        actual = d[0].status
        if actual == expected:
            print(f"pass  [{label}] -> {actual.value}"); passed += 1
        else:
            print(f"FAIL  [{label}] -> got {actual.value}, expected {expected.value}")
            print(f"        reasons: {d[0].reasons}"); failed += 1
    print(f"\n{passed} passed, {failed} failed, {len(CASES)} total")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
