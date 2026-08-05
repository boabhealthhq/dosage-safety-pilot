"""
30-second demo of the full pipeline: AI-generated clinical text in,
PASS/FLAG/BLOCK decisions + audit records out.

Run: python3 demo.py
"""

import json

from dosage_safety import PatientInfo, check_order, to_audit_record

# Pretend this came out of a clinical-facing AI product.
ai_generated_text = """
Patient presenting with fever, recommend paracetamol 15mg/kg PO 4-6 hourly PRN.
Also consider paracetamol 1200mg PO 6 hourly if pain is severe.
Alternatively, ibuprofen 8mg/kg PO 6-8 hourly PRN may be given for inflammation.
For the ear infection, start amoxicillin 40mg/kg PO BD.
For allergy symptoms, loratadine 10mg PO daily.
For croup, dexamethasone 0.3mg/kg PO stat.
For severe pain, fentanyl 1.5mcg/kg IN may be given.
"""

# Patient facts arrive as their own structured object - never parsed from the text above.
patient = PatientInfo(age_years=6, weight_kg=22)

print("Checking AI-generated text against patient: age=6, weight=22kg\n")

for decision in check_order(ai_generated_text, patient):
    print(f"[{decision.status.value}] {decision.extracted.raw_segment.strip()}")
    for reason in decision.reasons:
        print(f"    - {reason}")
    print()

    audit = to_audit_record(decision)
    print("    audit record:")
    print("   ", json.dumps(audit, indent=2).replace("\n", "\n    "))
    print()
