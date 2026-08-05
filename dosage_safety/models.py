"""
Shared data structures for the dosage safety pipeline.

Key design decision encoded here: PatientInfo is ALWAYS passed in as its own
structured object, separate from the order text. The Extract step never goes
looking for age/weight/height/sex inside prose - see README for why.
"""

from dataclasses import dataclass, field
from enum import Enum


class Status(str, Enum):
    PASS = "PASS"
    FLAG = "FLAG"
    BLOCK = "BLOCK"


@dataclass
class PatientInfo:
    """Structured patient facts, supplied directly by the calling product -
    never extracted from the order text."""
    age_years: float | None = None   # fractional allowed, e.g. 4/365 for a 4-day-old neonate
    weight_kg: float | None = None
    height_cm: float | None = None
    sex: str | None = None           # "M" / "F" / None
    # Only meaningful for opioids (fentanyl, oxycodone) - ignored entirely
    # by every other drug's check. None means "not stated" - opioid checks
    # treat that conservatively as opioid-naive, since assuming tolerance
    # without confirmation is the more dangerous direction to guess wrong in.
    opioid_tolerant: bool | None = None
    # Free-text allergy list, e.g. ["penicillin"]. Checked narrowly -
    # currently only amoxicillin cross-checks this (penicillin-class
    # allergy), not a general allergy system. Matched case-insensitively
    # as a substring, so "penicillin" matches "penicillin allergy (rash)"
    # too - deliberately permissive, since missing a real allergy is far
    # worse than an unnecessary flag.
    allergies: list | None = None
    # Free-text list of other medications the patient is currently on,
    # e.g. ["diazepam"]. Checked narrowly - currently only the two opioids
    # (fentanyl, oxycodone) cross-check this, for CNS depressants
    # specifically (benzodiazepines, other opioids, alcohol) - not a
    # general drug-interaction system.
    concurrent_medications: list | None = None


@dataclass
class ExtractedOrder:
    """Output of the Extract step - drug order text only, nothing about the patient."""
    raw_segment: str
    drug_name_raw: str          # exact alias text as it appeared, e.g. "Panadol" - for audit/display
    drug_canonical: str         # normalized key used to look up the rulebook, e.g. "paracetamol"
    dose_value: float | None
    dose_unit: str | None            # "mg", "g", "mg/kg"
    interval_low_hr: float | None
    interval_high_hr: float | None
    route: str | None = None
    prn: bool = False
    is_fuzzy_match: bool = False        # True if drug name matched via typo-tolerance, not exactly
    dose_is_range: bool = False         # True if the order stated a range (e.g. "500-1000mg")
    dose_range_low: float | None = None  # the lower bound, when dose_is_range is True
    dose_is_daily_total: bool = False   # True if the number is a DAILY total, not a per-dose figure


@dataclass
class NormalizedDrug:
    """Output of the Normalize step."""
    raw_name: str
    canonical_name: str
    rxcui: str


@dataclass
class Decision:
    """Output of the Decide step - what actually gets shown to a human."""
    status: Status
    reasons: list[str] = field(default_factory=list)
    rule_source: str | None = None
    drug: str | None = None
    extracted: ExtractedOrder | None = None
    patient: PatientInfo | None = None
