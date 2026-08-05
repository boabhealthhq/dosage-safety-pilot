"""Intranasal fentanyl test suite. python3 tests/test_fentanyl.py"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dosage_safety import PatientInfo, Status, check_order  # noqa: E402

CASES = [
    ("standard dose (1.5mcg/kg)",
     "fentanyl 1.5mcg/kg IN", PatientInfo(age_years=6, weight_kg=22), Status.PASS),

    ("low end of typical range (1.0mcg/kg)",
     "fentanyl 1.0mcg/kg IN", PatientInfo(age_years=8, weight_kg=28), Status.PASS),

    ("top of typical range (2.0mcg/kg)",
     "fentanyl 2.0mcg/kg IN", PatientInfo(age_years=10, weight_kg=32), Status.PASS),

    ("absolute mcg dose within range",
     "fentanyl 30mcg IN", PatientInfo(age_years=8, weight_kg=25), Status.PASS),

    ("no dose stated",
     "continue fentanyl PRN as charted", PatientInfo(age_years=8, weight_kg=25), Status.PASS),

    ("CRITICAL: mg/kg instead of mcg/kg - a 1000x unit confusion, must BLOCK",
     "fentanyl 1.5mg/kg IN", PatientInfo(age_years=6, weight_kg=22), Status.BLOCK),

    ("CRITICAL: mg instead of mcg absolute - must BLOCK",
     "fentanyl 50mg IN", PatientInfo(age_years=6, weight_kg=22), Status.BLOCK),

    ("exceeds the 100mcg absolute ceiling",
     "fentanyl 150mcg IN", PatientInfo(age_years=15, weight_kg=60), Status.BLOCK),

    ("rate above standard range - used in research settings, flagged not blocked",
     "fentanyl 2.5mcg/kg IN", PatientInfo(age_years=8, weight_kg=25), Status.FLAG),

    ("under 1 year - limited evidence base, flagged regardless of dose",
     "fentanyl 1.5mcg/kg IN", PatientInfo(age_years=0.5, weight_kg=7), Status.FLAG),

    ("opioid-tolerant patient - flagged not silently cleared",
     "fentanyl 1.5mcg/kg IN", PatientInfo(age_years=15, weight_kg=50, opioid_tolerant=True), Status.FLAG),

    ("redose interval below the 10-minute minimum",
     "fentanyl 1.5mcg/kg IN q5min", PatientInfo(age_years=8, weight_kg=25), Status.BLOCK),

    ("wrong route stated - out of scope for this rulebook",
     "fentanyl 50mcg IV", PatientInfo(age_years=30, weight_kg=70), Status.FLAG),

    ("patient age not provided",
     "fentanyl 30mcg IN", PatientInfo(weight_kg=25), Status.FLAG),

    ("patient weight not provided",
     "fentanyl 1.5mcg/kg IN", PatientInfo(age_years=8), Status.FLAG),
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
