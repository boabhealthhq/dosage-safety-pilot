"""
Log step. Turns a Decision into a structured, hashed audit record.

Kept intentionally minimal for v0 - no reviewing_user_id / reason_selected /
resolved_at fields yet, since the flag/override/acknowledge workflow is a
Layer-1 feature that hasn't been built into the engine yet. Those fields
are the natural next addition to this module once that workflow exists.
"""

import hashlib
import json
from datetime import datetime, timezone

from .models import Decision


def to_audit_record(decision: Decision) -> dict:
    patient = decision.patient
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "drug": decision.drug,
        "status": decision.status.value,
        "reasons": decision.reasons,
        "rule_source": decision.rule_source,
        "order_text": decision.extracted.raw_segment if decision.extracted else None,
        "patient": {
            "age_years": patient.age_years if patient else None,
            "weight_kg": patient.weight_kg if patient else None,
            "height_cm": patient.height_cm if patient else None,
            "sex": patient.sex if patient else None,
        },
    }
    payload = json.dumps(record, sort_keys=True).encode("utf-8")
    record["audit_hash"] = hashlib.sha256(payload).hexdigest()
    return record
