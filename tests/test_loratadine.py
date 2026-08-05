"""Loratadine test suite. python3 tests/test_loratadine.py"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dosage_safety import PatientInfo, Status, check_order  # noqa: E402

CASES = [
    ("standard young child (2-<6yr), 5mg",
     "loratadine 5mg PO daily", PatientInfo(age_years=4, weight_kg=16), Status.PASS),

    ("standard 6+/adult, 10mg",
     "Claritin 10mg PO daily", PatientInfo(age_years=30, weight_kg=70), Status.PASS),

    ("brand alias, young child",
     "Claritin 5mg PO daily", PatientInfo(age_years=3, weight_kg=14), Status.PASS),

    ("no dose stated",
     "continue loratadine as charted", PatientInfo(age_years=30, weight_kg=70), Status.PASS),

    ("under 2 years - avoid without guidance",
     "loratadine 2.5mg PO daily", PatientInfo(age_years=1.5, weight_kg=10), Status.FLAG),

    ("exceeds 10mg/day absolute ceiling",
     "loratadine 20mg PO daily", PatientInfo(age_years=30, weight_kg=70), Status.BLOCK),

    ("young child given the adult dose - flagged",
     "loratadine 10mg PO daily", PatientInfo(age_years=4, weight_kg=16), Status.FLAG),

    ("more frequent than once daily - blocked",
     "loratadine 10mg PO 12 hourly", PatientInfo(age_years=30, weight_kg=70), Status.BLOCK),

    ("mg/kg unit stated - not recognized, loratadine is age-based",
     "loratadine 0.5mg/kg PO daily", PatientInfo(age_years=4, weight_kg=16), Status.FLAG),

    ("patient age not provided",
     "loratadine 10mg PO daily", PatientInfo(weight_kg=70), Status.FLAG),

    ("IV route stated - no injectable formulation exists, flagged as likely transcription error",
     "loratadine 10mg IV daily", PatientInfo(age_years=30, weight_kg=70), Status.FLAG),
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
