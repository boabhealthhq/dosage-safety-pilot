"""Oxycodone test suite. python3 tests/test_oxycodone.py"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dosage_safety import PatientInfo, Status, check_order  # noqa: E402

CASES = [
    ("standard peds naive, low end (0.1mg/kg)",
     "oxycodone 0.1mg/kg PO 4 hourly", PatientInfo(age_years=8, weight_kg=25), Status.PASS),

    ("standard peds naive, high end (0.2mg/kg)",
     "oxycodone 0.2mg/kg PO 4 hourly", PatientInfo(age_years=8, weight_kg=25), Status.PASS),

    ("standard adult naive, low end",
     "oxycodone 5mg PO stat", PatientInfo(age_years=40, weight_kg=75), Status.PASS),

    ("standard adult naive, high end",
     "oxycodone 10mg PO stat", PatientInfo(age_years=40, weight_kg=75), Status.PASS),

    ("brand alias",
     "Endone 5mg PO stat", PatientInfo(age_years=40, weight_kg=75), Status.PASS),

    ("no dose stated",
     "continue oxycodone PRN as charted", PatientInfo(age_years=40, weight_kg=75), Status.PASS),

    ("infant under 6mo, reduced standard dosing",
     "oxycodone 0.03mg/kg PO 6 hourly", PatientInfo(age_years=0.3, weight_kg=6), Status.PASS),

    ("exceeds naive per-dose cap for children",
     "oxycodone 8mg PO 4 hourly", PatientInfo(age_years=8, weight_kg=25), Status.BLOCK),

    ("exceeds naive adult ceiling clearly",
     "oxycodone 25mg PO stat", PatientInfo(age_years=40, weight_kg=75), Status.BLOCK),

    ("above naive adult range but not extreme - verify tier",
     "oxycodone 15mg PO stat", PatientInfo(age_years=40, weight_kg=75), Status.FLAG),

    ("opioid-tolerant patient given higher dose - flagged not blocked",
     "oxycodone 15mg PO stat", PatientInfo(age_years=40, weight_kg=75, opioid_tolerant=True), Status.FLAG),

    ("infant under 6mo exceeds reduced cap",
     "oxycodone 0.1mg/kg PO 6 hourly", PatientInfo(age_years=0.3, weight_kg=6), Status.BLOCK),

    ("interval too frequent for paediatric naive dosing",
     "oxycodone 0.15mg/kg PO 2 hourly", PatientInfo(age_years=8, weight_kg=25), Status.BLOCK),

    ("patient age not provided",
     "oxycodone 5mg PO stat", PatientInfo(weight_kg=70), Status.FLAG),

    ("patient weight not provided for a child",
     "oxycodone 0.1mg/kg PO 4 hourly", PatientInfo(age_years=8), Status.FLAG),

    ("concurrent diazepam - flagged for respiratory depression risk",
     "oxycodone 0.1mg/kg PO 4 hourly", PatientInfo(age_years=8, weight_kg=25, concurrent_medications=["diazepam 2mg BD"]), Status.FLAG),

    ("IV route - flagged, this rulebook scoped to oral immediate-release only",
     "oxycodone 5mg IV stat", PatientInfo(age_years=40, weight_kg=75), Status.FLAG),
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
