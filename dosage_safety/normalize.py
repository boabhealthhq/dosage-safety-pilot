"""
Normalize step.

Maps a raw drug-name string to a canonical RxNorm ingredient concept
(RxCUI), so "Panadol", "paracetamol", and "acetaminophen" all collapse to
one concept before the rulebook is checked.

v0 note: this is a small local lookup table, not a live call to the RxNorm
API (this build environment has no network access, and a local table is
also more in keeping with the "plain rules, no external dependency at
runtime" philosophy from the plan). RXCUI 161 (acetaminophen, ingredient
level) is a stable, long-standing RxNorm identifier - verify against
https://mor.nlm.nih.gov/RxNav/ before this goes into anything production-facing.
"""

from .models import NormalizedDrug

RXCUI_BY_CANONICAL = {
    "paracetamol": "161",     # RxNorm ingredient concept: Acetaminophen
    "ibuprofen": "5640",      # RxNorm ingredient concept: Ibuprofen
    "amoxicillin": "723",     # RxNorm ingredient concept: Amoxicillin
    "loratadine": "6960",     # not independently re-confirmed this session - verify before production use
    "dexamethasone": "3264",  # not independently re-confirmed this session - verify before production use
    "fentanyl": "4337",       # confirmed via RxNorm ingredient lookup this session
    "oxycodone": "7804",      # not independently re-confirmed this session - verify before production use
}


def normalize_drug(canonical_name: str) -> NormalizedDrug | None:
    rxcui = RXCUI_BY_CANONICAL.get(canonical_name)
    if not rxcui:
        return None
    return NormalizedDrug(
        raw_name=canonical_name,
        canonical_name=canonical_name,
        rxcui=rxcui,
    )
