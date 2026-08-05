"""
Paracetamol test suite. Deliberately stdlib-only (no pytest) so a developer
can run this with nothing but `python3 tests/test_paracetamol.py` - no
install step, matching the "trivial setup" bar from the plan.

Run from the project root:
    python3 tests/test_paracetamol.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dosage_safety import PatientInfo, Status, check_order  # noqa: E402

# Each case: (label, order_text, patient, expected_status)
CASES = [
    # ---- normal / should PASS (the "do NOT flag" list) ----
    ("standard peds 15mg/kg 4-6hrly PRN",
     "paracetamol 15mg/kg PO 4-6 hourly PRN",
     PatientInfo(age_years=5, weight_kg=20), Status.PASS),

    ("standard peds fixed dose in mg, within band",
     "paracetamol 300mg PO 4-6 hourly PRN",
     PatientInfo(age_years=5, weight_kg=20), Status.PASS),

    ("standard adult 1g QID",
     "paracetamol 1g PO QID",
     PatientInfo(age_years=35, weight_kg=75), Status.PASS),

    ("standard adult 500mg 6hourly",
     "panadol 500mg PO 6 hourly",
     PatientInfo(age_years=40, weight_kg=68), Status.PASS),

    ("drug mentioned with no dose stated",
     "continue paracetamol as charted, otherwise stable",
     PatientInfo(age_years=5, weight_kg=20), Status.PASS),

    ("brand name alias resolves correctly (panadol)",
     "panadol 15mg/kg PO 4-6 hourly PRN",
     PatientInfo(age_years=2, weight_kg=12), Status.PASS),

    ("small neonate at correct 15mg/kg, 8hrly PRN",
     "paracetamol 15mg/kg PO 8 hourly PRN",
     PatientInfo(age_years=0.03, weight_kg=3.5), Status.PASS),

    ("adult underweight patient within reduced cap",
     "paracetamol 500mg PO QID",
     PatientInfo(age_years=70, weight_kg=45), Status.PASS),

    # ---- dangerous / should FLAG or BLOCK ----
    ("single peds dose exceeds 1g hard cap",
     "paracetamol 1200mg PO 6 hourly",
     PatientInfo(age_years=10, weight_kg=30), Status.BLOCK),

    ("peds dosing interval below 4hr minimum",
     "paracetamol 300mg PO 3 hourly",
     PatientInfo(age_years=5, weight_kg=20), Status.BLOCK),

    ("peds fixed frequent dosing pushes daily total over standard max",
     "paracetamol 15mg/kg PO 4 hourly",
     PatientInfo(age_years=5, weight_kg=20), Status.FLAG),

    ("adult daily total exceeds 4g/day cap",
     "paracetamol 1g PO 4 hourly",
     PatientInfo(age_years=30, weight_kg=80), Status.BLOCK),

    ("adult <50kg exceeds reduced 3g/day cap",
     "paracetamol 1g PO 6 hourly",
     PatientInfo(age_years=70, weight_kg=45), Status.BLOCK),

    ("neonate dose exceeds weight-based calculation and daily ceiling",
     "paracetamol 100mg PO 8 hourly",
     PatientInfo(age_years=0.03, weight_kg=3), Status.BLOCK),

    ("mg/kg dose rate above standard, fixed frequency pushes past verify ceiling",
     "paracetamol 25mg/kg PO 6 hourly",
     PatientInfo(age_years=6, weight_kg=22), Status.BLOCK),

    ("mg/kg dose rate modestly above standard, single dose only (no frequency stated)",
     "paracetamol 18mg/kg PO",
     PatientInfo(age_years=6, weight_kg=22), Status.FLAG),

    ("peds interval well below minimum (2 hourly)",
     "paracetamol 15mg/kg PO 2 hourly",
     PatientInfo(age_years=8, weight_kg=25), Status.BLOCK),

    # ---- missing-input handling (should FLAG, not silently pass) ----
    ("patient age not provided",
     "paracetamol 500mg PO QID",
     PatientInfo(weight_kg=70), Status.FLAG),

    ("patient weight not provided for a child",
     "paracetamol 15mg/kg PO 6 hourly",
     PatientInfo(age_years=6), Status.FLAG),

    ("IV route - flagged with specific formulation-error warning",
     "paracetamol 15mg/kg IV 4-6 hourly",
     PatientInfo(age_years=6, weight_kg=22), Status.FLAG),

    ("PO route stated explicitly - no route flag",
     "paracetamol 15mg/kg PO 4-6 hourly",
     PatientInfo(age_years=6, weight_kg=22), Status.PASS),
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
