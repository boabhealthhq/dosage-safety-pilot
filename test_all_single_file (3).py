"""
Dosage Safety Pilot v0 - full test suite, single-file version
(7 drugs: paracetamol, ibuprofen, amoxicillin, loratadine, dexamethasone,
fentanyl, oxycodone). v0.7 - same engine as demo.py. 111 dev cases total.

HOW TO USE:
Save this as test_all.py, then: python test_all.py
"""

import sys

import re
import json
import hashlib
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone
from typing import Optional, Protocol


# ============================================================
# MODELS
# ============================================================

from enum import Enum


class Status(str, Enum):
    PASS = "PASS"
    FLAG = "FLAG"
    BLOCK = "BLOCK"


@dataclass
class PatientInfo:
    """Structured patient facts, supplied directly by the calling product -
    never extracted from the order text."""
    age_years: Optional[float] = None   # fractional allowed, e.g. 4/365 for a 4-day-old neonate
    weight_kg: Optional[float] = None
    height_cm: Optional[float] = None
    sex: Optional[str] = None           # "M" / "F" / None
    # Only meaningful for opioids (fentanyl, oxycodone) - ignored entirely
    # by every other drug's check. None means "not stated" - opioid checks
    # treat that conservatively as opioid-naive, since assuming tolerance
    # without confirmation is the more dangerous direction to guess wrong in.
    opioid_tolerant: Optional[bool] = None


@dataclass
class ExtractedOrder:
    """Output of the Extract step - drug order text only, nothing about the patient."""
    raw_segment: str
    drug_name_raw: str          # exact alias text as it appeared, e.g. "Panadol" - for audit/display
    drug_canonical: str         # normalized key used to look up the rulebook, e.g. "paracetamol"
    dose_value: Optional[float]
    dose_unit: Optional[str]            # "mg", "g", "mg/kg"
    interval_low_hr: Optional[float]
    interval_high_hr: Optional[float]
    route: Optional[str] = None
    prn: bool = False
    is_fuzzy_match: bool = False        # True if drug name matched via typo-tolerance, not exactly
    dose_is_range: bool = False         # True if the order stated a range (e.g. "500-1000mg")
    dose_range_low: Optional[float] = None  # the lower bound, when dose_is_range is True
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
    rule_source: Optional[str] = None
    drug: Optional[str] = None
    extracted: Optional[ExtractedOrder] = None
    patient: Optional[PatientInfo] = None


# ============================================================
# RULEBOOK
# ============================================================

# ============================================================
# PARACETAMOL
# ============================================================

@dataclass(frozen=True)
class ParacetamolWeightBand:
    mg_per_kg_dose: float
    min_interval_hr: float
    max_interval_hr: float
    max_mg_per_kg_day: float
    dose_cap_mg: Optional[float] = None
    # up to here is standard - flag as "verify", don't hard-block, since
    # short-term inpatient dosing legitimately runs higher than the
    # standard max_mg_per_kg_day
    verify_mg_per_kg_day: Optional[float] = None


@dataclass(frozen=True)
class ParacetamolAdultBand:
    dose_range_mg: tuple
    min_interval_hr: float
    max_interval_hr: float
    max_mg_day_ge50kg: float
    max_mg_day_lt50kg: float


@dataclass(frozen=True)
class ParacetamolRule:
    rxcui: str
    sources: list
    neonate: ParacetamolWeightBand      # birth - 1 month
    paediatric: ParacetamolWeightBand   # 1 month - 18 years
    adult: ParacetamolAdultBand         # >= 18 years


PARACETAMOL = ParacetamolRule(
    rxcui="161",
    sources=[
        "Australian Medicines Handbook - Children's Dosing Companion",
        "Therapeutic Guidelines / eTG",
    ],
    neonate=ParacetamolWeightBand(
        mg_per_kg_dose=15,
        min_interval_hr=6,
        max_interval_hr=8,
        max_mg_per_kg_day=60,
    ),
    paediatric=ParacetamolWeightBand(
        mg_per_kg_dose=15,
        dose_cap_mg=1000,
        min_interval_hr=4,
        max_interval_hr=6,
        max_mg_per_kg_day=60,
        verify_mg_per_kg_day=90,
    ),
    adult=ParacetamolAdultBand(
        dose_range_mg=(500, 1000),
        min_interval_hr=4,
        max_interval_hr=6,
        max_mg_day_ge50kg=4000,
        max_mg_day_lt50kg=3000,
    ),
)


# ============================================================
# IBUPROFEN
# ============================================================

@dataclass(frozen=True)
class IbuprofenPaediatricBand:
    # Standard dosing is a RANGE (5-10mg/kg/dose), not a single point
    # figure like paracetamol's 15mg/kg - the "do NOT flag" list explicitly
    # includes the whole range.
    mg_per_kg_dose_low: float
    mg_per_kg_dose_high: float
    dose_cap_mg: float
    min_interval_hr: float
    max_interval_hr: float
    max_mg_per_kg_day: float
    max_mg_day_absolute: float  # whichever of this or the per-kg figure is lower


@dataclass(frozen=True)
class IbuprofenAdultBand:
    dose_range_mg: tuple
    min_interval_hr: float
    max_interval_hr: float
    max_mg_day_otc: float             # exceeding this is a FLAG/verify, not automatically wrong
    max_mg_day_prescription: float    # exceeding THIS is a hard BLOCK regardless of context


@dataclass(frozen=True)
class IbuprofenRule:
    rxcui: str
    sources: list
    # Avoid without specific clinician review below this age - not just a
    # different dosing band the way paracetamol's neonate band is. Some
    # OTC labelling is even more conservative (6mo) - 3mo used here as the
    # AMH-referenced threshold; verify against the live source.
    min_age_years: float
    paediatric: IbuprofenPaediatricBand   # 3 months - 18 years
    adult: IbuprofenAdultBand             # >= 18 years


IBUPROFEN = IbuprofenRule(
    rxcui="5640",
    sources=[
        "Australian Medicines Handbook - Children's Dosing Companion",
        "Poison Control / Drugs.com prescribing references (adult ceiling cross-check)",
    ],
    min_age_years=3 / 12,
    paediatric=IbuprofenPaediatricBand(
        mg_per_kg_dose_low=5,
        mg_per_kg_dose_high=10,
        dose_cap_mg=400,
        min_interval_hr=6,
        max_interval_hr=8,
        max_mg_per_kg_day=40,
        max_mg_day_absolute=2400,
    ),
    adult=IbuprofenAdultBand(
        dose_range_mg=(200, 400),
        min_interval_hr=4,
        max_interval_hr=6,
        max_mg_day_otc=1200,
        max_mg_day_prescription=3200,
    ),
)


# ============================================================
# AMOXICILLIN
# ============================================================
#
# Structurally different from the other two drugs, deliberately: the
# correct dose depends on WHAT'S BEING TREATED (strep throat vs pneumonia
# vs resistant otitis media), not just weight, so there is no single
# "standard mg/kg/dose" target the way paracetamol has 15mg/kg or
# ibuprofen has 5-10mg/kg. v0 does not have an indication field (that's a
# Layer 2 idea - see the plan doc), so the paediatric band is deliberately
# WIDE and only genuine outliers get flagged - checking is built around
# the DAILY total, not a per-dose rate.

@dataclass(frozen=True)
class AmoxicillinInfantBand:
    # Under 3 months: lower ceiling due to immature renal function - the
    # drug is still given at this age, just at a reduced max. A third,
    # different pattern again from ibuprofen's outright under-3mo
    # avoidance and paracetamol's simple dose-adjustment.
    max_mg_per_kg_day: float
    min_interval_hr: float


@dataclass(frozen=True)
class AmoxicillinPaediatricBand:
    max_mg_per_kg_day: float      # top of the legitimate high-dose range - do NOT flag up to here
    verify_mg_per_kg_day: float   # above this - flag/verify
    dose_cap_mg: float            # absolute per-dose hard cap regardless of weight
    max_mg_day_absolute: float    # never exceed regardless of weight-based calculation
    min_interval_hr: float


@dataclass(frozen=True)
class AmoxicillinAdultBand:
    dose_range_mg: tuple          # typical range - deliberately wide, not flagged within it
    max_mg_day_absolute: float
    min_interval_hr: float
    # Found missing via independent evaluation: without these, an unusually
    # large single adult dose (e.g. 1750mg, or 3g stat) went completely
    # unflagged as long as the DAILY total stayed under 4000mg - there was
    # no check on the single dose itself at all.
    typical_max_dose_mg: float     # above this - FLAG/verify (atypically large but not impossible)
    absolute_max_dose_mg: float    # above this - BLOCK regardless of frequency info


@dataclass(frozen=True)
class AmoxicillinRule:
    rxcui: str
    sources: list
    infant_under_3mo: AmoxicillinInfantBand
    paediatric: AmoxicillinPaediatricBand   # 3 months - 18 years
    adult: AmoxicillinAdultBand             # >= 18 years


AMOXICILLIN = AmoxicillinRule(
    rxcui="723",
    sources=[
        "Therapeutic Guidelines / eTG (indication-dependent dosing ranges)",
        "FDA label / clinical prescribing references (adult and high-dose ceiling cross-check)",
    ],
    infant_under_3mo=AmoxicillinInfantBand(
        max_mg_per_kg_day=30,
        min_interval_hr=12,
    ),
    paediatric=AmoxicillinPaediatricBand(
        max_mg_per_kg_day=90,
        verify_mg_per_kg_day=100,
        dose_cap_mg=2000,
        max_mg_day_absolute=4000,
        min_interval_hr=8,
    ),
    adult=AmoxicillinAdultBand(
        dose_range_mg=(250, 1000),
        max_mg_day_absolute=4000,
        min_interval_hr=8,
        typical_max_dose_mg=1000,
        absolute_max_dose_mg=4000,
    ),
)


# ============================================================
# LORATADINE
# ============================================================
#
# A fourth pattern again: age-banded with FIXED doses, not weight-based at
# all. Sources are explicit that this drug is dosed by age, not weight -
# unlike every other drug in this rulebook.

@dataclass(frozen=True)
class LoratadineRule:
    rxcui: str
    sources: list
    min_age_years: float          # avoid below this without clinician guidance
    young_band_max_age_years: float  # boundary between the two age bands
    young_band_dose_mg: float     # 2 - <6 years
    standard_dose_mg: float       # 6+ years and adults
    max_mg_day: float             # absolute ceiling regardless of band
    min_interval_hr: float        # once-daily only


LORATADINE = LoratadineRule(
    rxcui="6960",  # NOT independently re-confirmed via search this session - verify before relying on this
    sources=[
        "Mayo Clinic / Drugs.com consumer-facing OTC labelling",
        "Paediatric hospital OTC dosing charts (Children's Hospital Colorado, St Louis Children's)",
    ],
    min_age_years=2,
    young_band_max_age_years=6,
    young_band_dose_mg=5,
    standard_dose_mg=10,
    max_mg_day=10,
    min_interval_hr=24,
)


# ============================================================
# DEXAMETHASONE
# ============================================================
#
# Genuinely more indication-variable than even amoxicillin: legitimate
# croup dosing alone spans 0.15-0.6mg/kg depending on protocol (evidence
# shows 0.15mg/kg is non-inferior to the traditional 0.6mg/kg for most
# outcomes), and other indications (asthma, migraine) use different
# ranges again. Same "wide band, absolute cap" pattern as amoxicillin.

@dataclass(frozen=True)
class DexamethasoneBand:
    mg_per_kg_dose_low: float
    mg_per_kg_dose_high: float
    dose_cap_mg: float             # absolute per-dose cap regardless of weight
    verify_mg_per_kg: float        # above this rate - FLAG
    block_mg_per_kg: float         # above this rate - BLOCK
    min_interval_hr: float


@dataclass(frozen=True)
class DexamethasoneAdultBand:
    typical_range_mg: tuple
    verify_above_mg: float
    block_above_mg: float
    min_interval_hr: float


@dataclass(frozen=True)
class DexamethasoneRule:
    rxcui: str
    sources: list
    paediatric: DexamethasoneBand
    adult: DexamethasoneAdultBand


DEXAMETHASONE = DexamethasoneRule(
    rxcui="3264",  # NOT independently re-confirmed via search this session - verify before relying on this
    sources=[
        "Croup dosing evidence review (0.15mg/kg vs 0.6mg/kg comparative studies)",
        "AAP-referenced standard dosing (0.6mg/kg, max 16mg) for croup",
        "Asthma exacerbation dosing (0.3-0.6mg/kg/day) for cross-indication range check",
    ],
    paediatric=DexamethasoneBand(
        mg_per_kg_dose_low=0.15,
        mg_per_kg_dose_high=0.6,
        dose_cap_mg=16,
        verify_mg_per_kg=1.0,
        block_mg_per_kg=2.0,
        min_interval_hr=12,
    ),
    adult=DexamethasoneAdultBand(
        typical_range_mg=(4, 16),
        verify_above_mg=24,
        block_above_mg=40,
        min_interval_hr=12,
    ),
)


# ============================================================
# INTRANASAL FENTANYL (opioid - Schedule 8 / controlled substance)
# ============================================================
#
# DELIBERATELY MORE CONSERVATIVE than every other drug in this rulebook.
# Everything else here uses "wide legitimate band, only flag clear
# outliers" to minimise false positives. That philosophy would be actively
# dangerous applied to an opioid: a paracetamol dosing error causes harm
# over hours to days; an opioid dosing error can cause fatal respiratory
# depression in minutes. Bands here are narrower relative to the research
# literature on purpose - doses used safely in monitored research settings
# (up to ~2.6mcg/kg) are NOT treated as "normal, don't flag" the way
# amoxicillin's high-dose range is - they sit in the verify tier instead.
#
# STRUCTURAL LIMITATION, stated plainly: this tool has no way to assess
# opioid tolerance, concurrent CNS depressants (benzodiazepines, alcohol),
# or monitoring/naloxone availability - all of which materially change
# what a "safe" dose is. See PatientInfo.opioid_tolerant - when not
# explicitly set to True, every check here conservatively assumes
# opioid-naive. The check function attaches this limitation to every
# decision it returns, including PASS, not just flags - see engine.py.
#
# Scoped to PAEDIATRIC intranasal use only - the population and route this
# was researched for (ED procedural/acute pain analgesia). Adult and other
# routes (IV, transdermal, buccal) are NOT covered - see engine.py, which
# returns an explicit "not yet covered" FLAG for anything outside this
# scope rather than guessing.

@dataclass(frozen=True)
class FentanylIntranasalBand:
    standard_mcg_per_kg: float       # 1.5 - the best-evidenced standard single dose
    typical_range_low: float         # 1.0
    typical_range_high: float        # 2.0 - top of normal formulary range, do NOT flag up to here
    verify_mcg_per_kg: float         # above this - FLAG (used safely in research settings, not routine)
    dose_cap_mcg: float              # 100mcg - standard opioid-naive ceiling, BLOCK above this
    min_redose_interval_min: float   # minimum time between repeat doses
    min_age_years: float             # below this, evidence base is thin - FLAG for review regardless of dose


@dataclass(frozen=True)
class FentanylRule:
    rxcui: str
    sources: list
    paediatric_intranasal: FentanylIntranasalBand
    mandatory_disclaimer: str


FENTANYL = FentanylRule(
    rxcui="4337",  # confirmed via RxReasoner/RxNorm ingredient lookup this session
    sources=[
        "Royal Children's Hospital Melbourne Clinical Practice Guideline - Intranasal fentanyl",
        "Anderson et al. 2022, Pediatric Emergency Care - Safety of High-Dose Intranasal Fentanyl",
        "PECARN multicentre intranasal fentanyl dosing data",
    ],
    paediatric_intranasal=FentanylIntranasalBand(
        standard_mcg_per_kg=1.5,
        typical_range_low=1.0,
        typical_range_high=2.0,
        verify_mcg_per_kg=2.0,
        dose_cap_mcg=100,
        min_redose_interval_min=10,
        min_age_years=1,
    ),
    mandatory_disclaimer=(
        "Opioid safety depends on factors this tool does not assess: tolerance status, "
        "concurrent CNS depressants (benzodiazepines, alcohol), and monitoring/naloxone "
        "availability. This check assumes an opioid-naive patient unless opioid_tolerant=True "
        "is explicitly provided. Independent clinical judgement is required regardless of "
        "this tool's output."
    ),
)


# ============================================================
# OXYCODONE (opioid - Schedule 8 / controlled substance)
# ============================================================
#
# Same conservative design philosophy as fentanyl above - see that block's
# comment for the full reasoning. Scoped to IMMEDIATE-RELEASE, OPIOID-NAIVE
# initiation dosing only. Extended-release formulations and opioid-tolerant
# patient dosing are explicitly OUT of scope - both have real, different,
# and generally HIGHER dosing patterns that this rulebook does not encode,
# to avoid the tool silently applying naive-patient limits to a tolerant
# patient's legitimate regimen, or worse, applying tolerant-patient limits
# to a naive patient. See engine.py for how opioid_tolerant=True is
# handled (flagged for independent verification, not auto-cleared).

@dataclass(frozen=True)
class OxycodoneInfantBand:
    # under 6 months - reduced dosing per drugs.com (~25% of the standard
    # per-kg dose used for older children)
    mg_per_kg_dose: float
    dose_cap_mg: float
    block_mg_per_kg: float   # rate multiple that triggers a hard BLOCK, not just FLAG
    min_interval_hr: float


@dataclass(frozen=True)
class OxycodonePaediatricBand:
    mg_per_kg_dose_low: float
    mg_per_kg_dose_high: float
    dose_cap_mg: float             # standard opioid-naive per-dose ceiling for children
    verify_mg_per_kg: float
    min_interval_hr: float
    max_mg_per_kg_day: float


@dataclass(frozen=True)
class OxycodoneAdultBand:
    typical_range_mg: tuple        # opioid-naive initiation range
    verify_above_mg: float
    block_above_mg: float
    min_interval_hr: float


@dataclass(frozen=True)
class OxycodoneRule:
    rxcui: str
    sources: list
    infant_under_6mo: OxycodoneInfantBand
    paediatric: OxycodonePaediatricBand   # 6 months - 18 years, opioid-naive
    adult: OxycodoneAdultBand             # >= 18 years, opioid-naive initiation
    mandatory_disclaimer: str


OXYCODONE = OxycodoneRule(
    rxcui="7804",  # NOT independently re-confirmed via search this session - verify before relying on this
    sources=[
        "WHO pediatric opioid-naive starting dose guidance",
        "Drugs.com dosage reference (opioid-naive adult and infant adjustment)",
        "General pediatric opioid prescribing guideline aggregation (verify against live AMH/eTG)",
    ],
    infant_under_6mo=OxycodoneInfantBand(
        mg_per_kg_dose=0.03,   # ~25% of the 0.1-0.125mg/kg standard low end
        dose_cap_mg=1,         # tightened from an earlier, uncalibrated 2mg - a correctly-dosed
                                # infant in the typical 3-8kg range receives well under 1mg
        block_mg_per_kg=0.075, # 2.5x the standard reduced rate - a hard BLOCK, not just FLAG,
                                # since this is the most vulnerable population in the rulebook
        min_interval_hr=6,
    ),
    paediatric=OxycodonePaediatricBand(
        mg_per_kg_dose_low=0.1,
        mg_per_kg_dose_high=0.2,
        dose_cap_mg=5,
        verify_mg_per_kg=0.2,
        min_interval_hr=4,
        # 1.5, not the earlier 1.0: the standard top-of-range dose (0.2mg/kg)
        # given at the standard minimum interval (q4h = 6x/day) computes to
        # 1.2mg/kg/day - a ceiling of 1.0 would have blocked a correctly-dosed
        # standard order, an internal inconsistency caught by testing, not a
        # sourced clinical figure that changed.
        max_mg_per_kg_day=1.5,
    ),
    adult=OxycodoneAdultBand(
        typical_range_mg=(5, 10),
        verify_above_mg=10,
        block_above_mg=20,
        min_interval_hr=3,
    ),
    mandatory_disclaimer=(
        "Opioid safety depends on factors this tool does not assess: tolerance status, "
        "concurrent CNS depressants (benzodiazepines, alcohol), and monitoring/naloxone "
        "availability. This check assumes an opioid-naive patient and IMMEDIATE-RELEASE "
        "formulation unless opioid_tolerant=True is explicitly provided - extended-release "
        "dosing is NOT covered and follows a different, generally higher pattern. Independent "
        "clinical judgement is required regardless of this tool's output."
    ),
)


# ============================================================
# EXTRACT
# ============================================================

import re

# v0: paracetamol only. Add new aliases here as new drugs are added to the rulebook.
# "pcm" added as a common real-world shorthand, not a typo - kept separate from
# the fuzzy-typo mechanism below.
DRUG_ALIASES = {
    "paracetamol": [
        "paracetamol", "panadol", "panamax", "dymadon",
        "acetaminophen", "tylenol", "apap", "pcm",
    ],
    "ibuprofen": [
        "ibuprofen", "nurofen", "brufen", "advil", "motrin", "ibu",
    ],
    "amoxicillin": [
        "amoxicillin", "amoxil", "moxatag", "amoxycillin",
    ],
    "loratadine": [
        "loratadine", "claritin",
    ],
    "dexamethasone": [
        "dexamethasone", "decadron", "dex",
    ],
    "fentanyl": [
        "fentanyl",
    ],
    "oxycodone": [
        "oxycodone", "oxycontin", "roxicodone", "endone",
    ],
}

# Matches a number with OR without comma thousand-separators - e.g. "500",
# "5000", "1,000", "12,500" all match correctly with no digits lost. The
# naive fix (just allowing commas anywhere) would have broken plain
# uncommaed 4+ digit numbers like "5000" - which matters a lot here, since
# those are exactly the large, dangerous doses this tool most needs to
# catch correctly, not the ones to risk truncating.
_NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"

# Unit alternation - ORDER MATTERS: longer/more specific patterns must come
# before their shorter prefixes (e.g. "mg/kg/day" before "mg/kg"), since
# regex alternation takes the first alternative that matches, not the
# longest. The "/day" variants mark an explicitly-stated DAILY TOTAL rather
# than a per-dose figure - found via independent evaluation to be a real,
# repeated source of dangerous misreads (e.g. "90mg/kg/day divided BD" was
# being read as 90mg/kg PER DOSE, doubling the real rate).
_UNIT_PATTERN = r"(mg/kg/day|mg/kg/24h|mg/kg|mg/day|mg|g/day|g|mcg/kg/day|mcg/kg|mcg)"

# Single-value dose, e.g. "500mg", "15mg/kg", "1,000mg", "90mg/kg/day"
DOSE_RE = re.compile(
    rf"({_NUMBER})\s*{_UNIT_PATTERN}\b", re.IGNORECASE
)

# Range dose, e.g. "500-1000mg" - checked BEFORE the single-value pattern
DOSE_RANGE_RE = re.compile(
    rf"({_NUMBER})\s*-\s*({_NUMBER})\s*{_UNIT_PATTERN}\b", re.IGNORECASE
)

# "divided" phrasing (e.g. "40mg/kg divided q8h") is a second, less explicit
# way of stating a daily total rather than a per-dose figure - same
# underlying issue as the "/day" units above, different wording.
DIVIDED_RE = re.compile(r"\bdivided\b", re.IGNORECASE)

INTERVAL_RE = re.compile(
    r"(\d+)\s*(?:-|to)?\s*(\d+)?\s*hourly"
    r"|q(\d+)(?:-(\d+))?h"
    r"|every\s+(\d+)\s*(?:-|to)?\s*(\d+)?\s*hours?",
    re.IGNORECASE,
)

# Minute-scale intervals - needed for opioid redosing instructions
# ("q5min", "every 10 minutes"), which the hour-only pattern above can't
# express. Converted to fractional hours for storage, since
# interval_low_hr/high_hr are always in hours.
MINUTE_INTERVAL_RE = re.compile(
    r"q(\d+)\s*min(?:ute)?s?\b"
    r"|every\s+(\d+)\s*min(?:ute)?s?\b",
    re.IGNORECASE,
)

ABBREV_INTERVALS = {
    "qid": (6, 6), "tds": (8, 8), "tid": (8, 8),
    "bd": (12, 12), "bid": (12, 12),
}
# "od" and "daily" are checked separately, and only as a fallback AFTER an
# explicit numeric interval has been tried - "daily" in particular shows up
# inside other phrases ("divided daily dose", "total daily amount") where
# it does NOT mean "once a day", and was found to shadow an explicit "q6h"
# stated elsewhere in the same order.
AMBIGUOUS_ABBREV_INTERVALS = {
    "od": (24, 24), "daily": (24, 24),
}

# Spelled-out frequency phrases ("three times a day", "twice daily") -
# found by independent evaluation to cause real dangerous misses, since
# only numeric/abbreviated forms had been tested before. Checked against
# the DIGIT form, after word-number normalization has already run.
_TIMES_PER_DAY_RE = re.compile(
    r"\b(\d+)\s*times?\s*(?:a\s+|per\s+)?(?:day|daily)\b", re.IGNORECASE
)
_SPECIAL_FREQUENCY_WORDS = [
    (re.compile(r"\bonce\s+(?:a\s+|per\s+)?(?:day|daily)\b", re.IGNORECASE), (24, 24)),
    (re.compile(r"\btwice\s+(?:a\s+|per\s+)?(?:day|daily)\b", re.IGNORECASE), (12, 12)),
    (re.compile(r"\bthrice\s+(?:a\s+|per\s+)?(?:day|daily)\b", re.IGNORECASE), (8, 8)),
]

# Dotted clinical shorthand (q.i.d., t.i.d. etc.) normalized to the plain
# form above BEFORE anything else runs, so periods inside an abbreviation
# never get mistaken for a sentence break. Longer patterns listed first so
# e.g. "t.i.d." isn't partially matched by a shorter, unrelated pattern.
_DOTTED_ABBREVS = [
    (re.compile(r"\bq\.i\.d\.?", re.IGNORECASE), "qid"),
    (re.compile(r"\bt\.i\.d\.?", re.IGNORECASE), "tid"),
    (re.compile(r"\bb\.i\.d\.?", re.IGNORECASE), "bid"),
    (re.compile(r"\bp\.r\.n\.?", re.IGNORECASE), "prn"),
    (re.compile(r"\bq\.d\.?", re.IGNORECASE), "od"),
    (re.compile(r"\bo\.d\.?", re.IGNORECASE), "od"),
]

# Spelled-out numbers, for interval phrases like "every four hours" -
# found by independent evaluation to cause real dangerous misses, since
# every prior stress-test round used numeric or abbreviated forms only.
_WORD_NUMBERS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
    "eleven": "11", "twelve": "12",
}
_WORD_NUMBER_RE = re.compile(r"\b(" + "|".join(_WORD_NUMBERS.keys()) + r")\b", re.IGNORECASE)
_TWENTY_FOUR_RE = re.compile(r"\btwenty[\s-]?four\b", re.IGNORECASE)

# "20mg per kilo" / "20mg per kg" -> normalized to "20mg/kg" so the existing
# dose regex can read it. A second real gap found by independent evaluation.
_PER_KG_RE = re.compile(
    rf"({_NUMBER})\s*mg\s+per\s*(?:kilo(?:gram)?|kg)\b", re.IGNORECASE
)

# Spelled-out units ("1 gram" instead of "1g") - a third real gap found by
# independent evaluation. Order-safe due to \b word boundaries: "grams"
# inside "milligrams" has no boundary before it, so won't be double-matched.
_UNIT_WORDS = [
    (re.compile(r"\bmilligrams?\b", re.IGNORECASE), "mg"),
    (re.compile(r"\bmicrograms?\b", re.IGNORECASE), "mcg"),
    (re.compile(r"\bgrams?\b", re.IGNORECASE), "g"),
]

# "divided into two doses" (no explicit interval unit) - treated as an
# interval-equivalent phrase, same idea as "twice daily".
_DIVIDED_INTO_N_RE = re.compile(r"\bdivided\s+into\s+(\d+)\s+doses?\b", re.IGNORECASE)

ROUTE_RE = re.compile(r"\b(PO|IV|IM|PR|SL|SC|subcut)\b", re.IGNORECASE)
# Deliberately case-SENSITIVE, unlike the other routes above: lowercase
# "in" is extremely common ordinary English ("given in the ED", "increase
# in dose") and would cause frequent false route captures if matched
# case-insensitively. Uppercase "IN" as a route abbreviation is a much
# safer signal.
INTRANASAL_ROUTE_RE = re.compile(r"\bIN\b")
PRN_RE = re.compile(r"\bPRN\b", re.IGNORECASE)

# A window-ending "sentence break": . ; or ! - but NOT when it's a decimal
# point (digit immediately before AND after), so "2.5g" is never mistaken
# for two sentences.
TERMINATOR_RE = re.compile(r"(?<!\d)[.;!](?!\d)")

# Fuzzy typo tolerance only applies to aliases at least this long, and only
# allows a single-character edit - short words are too risky to fuzzy-match
# (too easy to collide with an unrelated common word).
MIN_FUZZY_ALIAS_LEN = 5
MAX_FUZZY_EDIT_DISTANCE = 1


def _normalize_dotted_abbrevs(text: str) -> str:
    for pattern, replacement in _DOTTED_ABBREVS:
        text = pattern.sub(replacement, text)
    return text


def _normalize_word_numbers(text: str) -> str:
    text = _TWENTY_FOUR_RE.sub("24", text)
    return _WORD_NUMBER_RE.sub(lambda m: _WORD_NUMBERS[m.group(1).lower()], text)


def _normalize_per_kg_phrasing(text: str) -> str:
    return _PER_KG_RE.sub(lambda m: f"{m.group(1)}mg/kg", text)


def _normalize_unit_words(text: str) -> str:
    for pattern, replacement in _UNIT_WORDS:
        text = pattern.sub(replacement, text)
    return text


def _levenshtein(a: str, b: str) -> int:
    """Standard edit distance - how many single-character edits turn a into b."""
    if a == b:
        return 0
    m, n = len(a), len(b)
    if m == 0:
        return n
    if n == 0:
        return m
    prev = list(range(n + 1))
    for i in range(1, m + 1):
        curr = [i] + [0] * n
        for j in range(1, n + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[n]


def _find_all_alias_hits(text: str):
    """Find every drug-alias occurrence in the whole text, exact match first.
    Returns a list of (start, end, canonical, matched_text, is_fuzzy),
    sorted by position. Falls back to single-character-typo tolerance only
    for words with no exact match anywhere, so a real typo doesn't go
    completely unseen - but always comes back flagged as fuzzy, never
    silently treated as certain."""
    hits = []
    low = text.lower()

    for canonical, aliases in DRUG_ALIASES.items():
        for alias in aliases:
            for m in re.finditer(rf"\b{re.escape(alias)}\b", low):
                hits.append((m.start(), m.end(), canonical, text[m.start():m.end()], False))

    exact_spans = {(h[0], h[1]) for h in hits}

    # Fuzzy fallback: only consider words that didn't already get an exact hit
    for m in re.finditer(r"\b[a-zA-Z]+\b", low):
        start, end = m.start(), m.end()
        if any(start < e and end > s for s, e in exact_spans):
            continue  # overlaps a real match, skip
        word = low[start:end]
        if len(word) < MIN_FUZZY_ALIAS_LEN:
            continue
        for canonical, aliases in DRUG_ALIASES.items():
            for alias in aliases:
                if len(alias) < MIN_FUZZY_ALIAS_LEN:
                    continue  # too short to fuzzy-match safely
                if abs(len(word) - len(alias)) > MAX_FUZZY_EDIT_DISTANCE:
                    continue
                if _levenshtein(word, alias) == MAX_FUZZY_EDIT_DISTANCE:
                    hits.append((start, end, canonical, text[start:end], True))
                    break

    hits.sort(key=lambda h: h[0])
    return hits


def _search_dose(text_span: str):
    """Try the range pattern first, then the single-value pattern. Returns
    (kind, match) where kind is 'range' or 'single', or None if neither matched."""
    m = DOSE_RANGE_RE.search(text_span)
    if m:
        return ("range", m)
    m = DOSE_RE.search(text_span)
    if m:
        return ("single", m)
    return None


def extract_orders(text: str) -> list[ExtractedOrder]:
    """For every drug-alias occurrence in the text, look both forward and
    backward - bounded by the next/previous drug alias or the nearest real
    sentence break, whichever is closer - and pull the dose from whichever
    direction has the closer match. Handles both "paracetamol 500mg" and
    "500mg of paracetamol" phrasing. Interval/route/PRN are still read
    forward-only, since no case has yet shown a need to search backward
    for those. Never crosses into a different drug's numbers, and never
    stops at a bare line break within the same order."""
    text = _normalize_dotted_abbrevs(text)
    text = _normalize_word_numbers(text)
    text = _normalize_per_kg_phrasing(text)
    text = _normalize_unit_words(text)
    hits = _find_all_alias_hits(text)
    results = []

    for i, (start, end, canonical, alias_text, is_fuzzy) in enumerate(hits):
        window_end = len(text)
        if i + 1 < len(hits):
            window_end = min(window_end, hits[i + 1][0])

        term_match = TERMINATOR_RE.search(text, end, window_end)
        if term_match:
            window_end = term_match.start()

        # Backward bound: end of the previous alias, or the nearest
        # preceding sentence terminator - whichever is closer (later).
        back_bound = 0
        if i > 0:
            back_bound = hits[i - 1][1]
        last_back_term = None
        for tm in TERMINATOR_RE.finditer(text, back_bound, start):
            last_back_term = tm
        found_real_terminator = last_back_term is not None
        if last_back_term:
            back_bound = max(back_bound, last_back_term.end())

        # Only search backward when this is the FIRST alias in the text
        # (nothing before it to conflict with) or a real terminator
        # separates this order from the previous alias's own territory.
        # Without one, the gap between two consecutive aliases belongs to
        # the PREVIOUS alias's forward search - letting this alias's
        # backward search reach into it risks stealing the previous drug's
        # dose. Confirmed as a real bug: in "fentanyl 1.5mcg/kg IN and
        # oxycodone 0.1mg/kg...", oxycodone's backward search was pulling
        # in fentanyl's own dose from the shared, unpunctuated gap.
        allow_backward_search = (i == 0) or found_real_terminator
        backward_span = text[back_bound:start] if allow_backward_search else ""
        forward_span = text[start:window_end]

        back_result = _search_dose(backward_span) if backward_span else None
        fwd_result = _search_dose(forward_span)

        use_backward = False
        if back_result and fwd_result:
            back_distance = len(backward_span) - back_result[1].end()
            fwd_distance = fwd_result[1].start()
            use_backward = back_distance < fwd_distance
        elif back_result and not fwd_result:
            use_backward = True

        if use_backward:
            window = text[back_bound:window_end]
        else:
            window = text[start:window_end]
        clean_window = re.sub(r"\s+", " ", window).strip()
        # interval/route/PRN stay forward-only regardless of which
        # direction the dose was found in - no case has shown a need to
        # search backward for these, and doing so unconditionally would
        # risk picking up an unrelated interval mentioned before this order.
        forward_clean = re.sub(r"\s+", " ", forward_span).strip()

        range_match = DOSE_RANGE_RE.search(clean_window)
        dose_value = None
        dose_unit = None
        dose_is_range = False
        dose_range_low = None
        if range_match:
            dose_range_low = float(range_match.group(1).replace(",", ""))
            dose_value = float(range_match.group(2).replace(",", ""))  # conservative: use the upper bound
            dose_unit = range_match.group(3).lower()
            dose_is_range = True
        else:
            dose_match = DOSE_RE.search(clean_window)
            if dose_match:
                dose_value = float(dose_match.group(1).replace(",", ""))
                dose_unit = dose_match.group(2).lower()

        # Daily-total detection: either an explicit "/day" unit (e.g.
        # "90mg/kg/day") or the word "divided" nearby (e.g. "40mg/kg divided
        # q8h") both mean the extracted number is a DAILY total, not a
        # per-dose figure - the engine needs to know this to avoid reading
        # it as (much larger) per-dose amount. The "/day" suffix is then
        # stripped so downstream mg/g conversion logic doesn't need to
        # know about it separately.
        dose_is_daily_total = False
        if dose_unit and dose_unit.endswith("/day"):
            dose_unit = dose_unit[:-4]
            dose_is_daily_total = True
        elif dose_value is not None and DIVIDED_RE.search(clean_window):
            dose_is_daily_total = True

        lo, hi = _parse_interval(forward_clean)
        route_match = ROUTE_RE.search(forward_clean)
        if route_match:
            route = route_match.group(1).upper()
        else:
            intranasal_match = INTRANASAL_ROUTE_RE.search(forward_clean)
            route = "IN" if intranasal_match else None
        prn = bool(PRN_RE.search(forward_clean))

        results.append(
            ExtractedOrder(
                raw_segment=clean_window,
                drug_name_raw=alias_text,
                drug_canonical=canonical,
                dose_value=dose_value,
                dose_unit=dose_unit,
                interval_low_hr=lo,
                interval_high_hr=hi,
                route=route,
                prn=prn,
                is_fuzzy_match=is_fuzzy,
                dose_is_range=dose_is_range,
                dose_range_low=dose_range_low,
                dose_is_daily_total=dose_is_daily_total,
            )
        )

    return results


def _parse_interval(segment: str):
    low = segment.lower()

    for pattern, (lo, hi) in _SPECIAL_FREQUENCY_WORDS:
        if pattern.search(low):
            return lo, hi

    times_match = _TIMES_PER_DAY_RE.search(low)
    if times_match:
        n = int(times_match.group(1))
        if n > 0:
            interval = 24 / n
            return interval, interval

    divided_into_match = _DIVIDED_INTO_N_RE.search(low)
    if divided_into_match:
        n = int(divided_into_match.group(1))
        if n > 0:
            interval = 24 / n
            return interval, interval

    minute_match = MINUTE_INTERVAL_RE.search(low)
    if minute_match:
        minutes = int(minute_match.group(1) or minute_match.group(2))
        if minutes > 0:
            interval_hr = minutes / 60
            return interval_hr, interval_hr

    for word, (lo, hi) in ABBREV_INTERVALS.items():
        if re.search(rf"\b{word}\b", low):
            return lo, hi

    m = INTERVAL_RE.search(segment)
    if m:
        nums = [g for g in m.groups() if g is not None]
        if nums:
            if len(nums) == 1:
                v = float(nums[0])
                return v, v
            return float(nums[0]), float(nums[1])

    # Ambiguous fallback - checked LAST, only if nothing more explicit
    # matched. "daily"/"od" often appear inside other phrases ("total daily
    # dose") where they don't literally mean "once a day".
    for word, (lo, hi) in AMBIGUOUS_ABBREV_INTERVALS.items():
        if re.search(rf"\b{word}\b", low):
            return lo, hi

    return None, None


# ============================================================
# NORMALIZE
# ============================================================

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


# ============================================================
# ENGINE
# ============================================================

NEONATE_MAX_AGE_YEARS = 1 / 12  # 1 month
PAEDIATRIC_MAX_AGE_YEARS = 18


def _validate_patient(patient: PatientInfo) -> str | None:
    """Returns a plain-language error if patient data is implausible enough
    that dosing math shouldn't run on it at all, None if it's fine. Found
    necessary via a robustness pass: zero weight caused a ZeroDivisionError
    crash, and negative weight silently produced a false PASS (the two
    negatives cancelled out in a later division, giving a coincidentally
    "normal-looking" number rather than any real validation catching it)."""
    if patient.weight_kg is not None:
        if patient.weight_kg <= 0:
            return (f"Patient weight ({patient.weight_kg}kg) is not a plausible positive "
                    f"value - cannot calculate dosing.")
        if patient.weight_kg > 300:
            return f"Patient weight ({patient.weight_kg}kg) is outside a plausible human range - verify this value."
    if patient.age_years is not None:
        if patient.age_years < 0:
            return f"Patient age ({patient.age_years} years) cannot be negative - verify this value."
        if patient.age_years > 120:
            return f"Patient age ({patient.age_years} years) is outside a plausible human range - verify this value."
    return None


def _dose_in_mg(order: ExtractedOrder) -> float | None:
    """Convert extracted dose to plain mg. mg/kg doses need patient weight,
    handled by the caller - this just normalizes units where no weight is
    needed."""
    if order.dose_value is None or order.dose_unit is None:
        return None
    if order.dose_unit == "mg":
        return order.dose_value
    if order.dose_unit == "g":
        return order.dose_value * 1000
    return None  # mcg/mg-per-kg handled separately where relevant


def _doses_per_day(order: ExtractedOrder) -> float | None:
    """Uses the SHORTER interval (more frequent dosing) as the worst case
    for a daily-total calculation - a '4-6 hourly' order could legitimately
    be given as often as every 4 hours."""
    interval = order.interval_low_hr or order.interval_high_hr
    if not interval:
        return None
    return 24 / interval


def _check_paracetamol(order: ExtractedOrder, patient: PatientInfo) -> Decision:
    reasons: list[str] = []
    status = Status.PASS
    rule = PARACETAMOL

    # Always surface these, regardless of what else fires - a fuzzy match or
    # a dose range is worth a human's attention even on an otherwise-clean order.
    if order.is_fuzzy_match:
        reasons.append(
            f"Drug name '{order.drug_name_raw}' did not exactly match a known alias - "
            f"matched via typo-tolerance to 'paracetamol'. Verify this is correct."
        )
    if order.dose_is_range:
        reasons.append(
            f"Dose stated as a range ({order.dose_range_low:.0f}-{order.dose_value:.0f}{order.dose_unit}) - "
            f"checked against the upper bound ({order.dose_value:.0f}{order.dose_unit})."
        )

    validation_error = _validate_patient(patient)
    if validation_error:
        return Decision(
            status=Status.FLAG,
            reasons=reasons + [validation_error],
            drug="paracetamol", extracted=order, patient=patient,
        )

    if order.dose_value is None:
        return Decision(
            status=Status.PASS,
            reasons=reasons + ["Drug mentioned with no dose stated - nothing to check."],
            drug="paracetamol", extracted=order, patient=patient,
        )

    if patient.age_years is None:
        return Decision(
            status=Status.FLAG,
            reasons=reasons + ["Patient age not provided - cannot select the correct dosing band."],
            drug="paracetamol", extracted=order, patient=patient,
        )

    dose_mg = _dose_in_mg(order)
    doses_per_day = _doses_per_day(order)

    # ---- band selection ----
    if patient.age_years < NEONATE_MAX_AGE_YEARS:
        band = rule.neonate
        band_name = "neonate (birth-1mo)"
    elif patient.age_years < PAEDIATRIC_MAX_AGE_YEARS:
        band = rule.paediatric
        band_name = "paediatric (1mo-18yr)"
    else:
        band = rule.adult
        band_name = "adult"

    # ---- paediatric / neonate: weight-based ----
    if band_name != "adult":
        if patient.weight_kg is None:
            return Decision(
                status=Status.FLAG,
                reasons=reasons + [f"Patient weight not provided - required for {band_name} weight-based dosing."],
                drug="paracetamol", extracted=order, patient=patient,
            )

        if order.dose_unit == "mg/kg":
            if order.dose_is_daily_total:
                # the mg/kg figure is a stated DAILY total, not per-dose -
                # convert to a true per-dose equivalent before checking the
                # rate, rather than comparing a daily figure against a
                # per-dose standard (found to cause dangerous false BLOCKs
                # and false PASSes via independent evaluation)
                raw_daily_mg = order.dose_value * patient.weight_kg
                if doses_per_day:
                    dose_mg = raw_daily_mg / doses_per_day
                    per_dose_rate = dose_mg / patient.weight_kg
                    reasons.append(
                        f"Dose interpreted as a daily total ({order.dose_value:.0f}mg/kg/day) - "
                        f"per-dose equivalent is ~{per_dose_rate:.1f}mg/kg."
                    )
                    if per_dose_rate > band.mg_per_kg_dose * 1.1:
                        status = Status.FLAG
                        reasons.append(
                            f"Per-dose equivalent ({per_dose_rate:.1f}mg/kg) exceeds the standard "
                            f"{band.mg_per_kg_dose}mg/kg/dose for {band_name}."
                        )
                else:
                    dose_mg = None
                    status = Status.FLAG
                    reasons.append(
                        f"Dose stated as a daily total ({order.dose_value:.0f}mg/kg/day) but the "
                        f"dosing frequency could not be determined - cannot verify the per-dose "
                        f"amount is safe."
                    )
            else:
                # dose already expressed per-kg PER DOSE in the text - check the rate itself
                if order.dose_value > band.mg_per_kg_dose * 1.1:
                    status, reasons = Status.FLAG, reasons + [
                        f"Dose of {order.dose_value}mg/kg exceeds the standard "
                        f"{band.mg_per_kg_dose}mg/kg/dose for {band_name}."
                    ]
                dose_mg = order.dose_value * patient.weight_kg
        elif dose_mg is not None:
            if order.dose_is_daily_total:
                raw_daily_mg = dose_mg
                if doses_per_day:
                    dose_mg = raw_daily_mg / doses_per_day
                    reasons.append(
                        f"Dose interpreted as a daily total (~{raw_daily_mg:.0f}mg/day) - "
                        f"per-dose equivalent calculated as ~{dose_mg:.0f}mg."
                    )
                else:
                    dose_mg = None
                    status = Status.FLAG
                    reasons.append(
                        f"Dose stated as a daily total (~{raw_daily_mg:.0f}mg/day) but the dosing "
                        f"frequency could not be determined - cannot verify the per-dose amount is safe."
                    )
            if dose_mg is not None:
                expected_mg = band.mg_per_kg_dose * patient.weight_kg
                cap = band.dose_cap_mg
                if cap and dose_mg > cap:
                    status, reasons = Status.BLOCK, reasons + [
                        f"Single dose of {dose_mg:.0f}mg exceeds the {cap}mg hard per-dose cap for {band_name}."
                    ]
                elif dose_mg > expected_mg * 1.15:
                    status, reasons = Status.FLAG, reasons + [
                        f"Single dose of {dose_mg:.0f}mg exceeds the weight-based calculation "
                        f"({band.mg_per_kg_dose}mg/kg x {patient.weight_kg}kg = {expected_mg:.0f}mg) for this patient."
                    ]

        # interval check
        if order.interval_low_hr is not None and order.interval_low_hr < band.min_interval_hr:
            status, reasons = Status.BLOCK, reasons + [
                f"Dosing interval of {order.interval_low_hr}hrly is below the "
                f"{band.min_interval_hr}hrly minimum for {band_name}."
            ]

        # Daily total check - only meaningful when the interval is a single,
        # fixed number (e.g. "6 hourly", "QID"). A stated range (e.g.
        # "4-6 hourly", especially PRN) doesn't tell us how many doses/day
        # will actually be given, so we don't guess at a worst case here -
        # the interval-minimum check above already catches genuinely
        # too-frequent fixed dosing.
        fixed_interval = (
            order.interval_low_hr is not None
            and order.interval_low_hr == order.interval_high_hr
        )
        if dose_mg is not None and doses_per_day is not None and fixed_interval:
            daily_mg_per_kg = (dose_mg * doses_per_day) / patient.weight_kg
            verify_threshold = (
                band.verify_mg_per_kg_day
                if band.verify_mg_per_kg_day is not None
                else band.max_mg_per_kg_day
            )
            if daily_mg_per_kg > verify_threshold:
                status, reasons = Status.BLOCK, reasons + [
                    f"Implied daily total (~{daily_mg_per_kg:.0f}mg/kg/day) exceeds even the short-term "
                    f"inpatient tolerance ({verify_threshold}mg/kg/day) for {band_name}."
                ]
            elif daily_mg_per_kg > band.max_mg_per_kg_day:
                if status != Status.BLOCK:
                    status = Status.FLAG
                reasons.append(
                    f"Implied daily total (~{daily_mg_per_kg:.0f}mg/kg/day) exceeds the standard "
                    f"{band.max_mg_per_kg_day}mg/kg/day max - verify if intentional short-term inpatient dosing."
                )

    # ---- adult: fixed-dose based ----
    else:
        if dose_mg is not None and order.dose_is_daily_total:
            raw_daily_mg = dose_mg
            if doses_per_day:
                dose_mg = raw_daily_mg / doses_per_day
                reasons.append(
                    f"Dose interpreted as a daily total (~{raw_daily_mg:.0f}mg/day) - "
                    f"per-dose equivalent calculated as ~{dose_mg:.0f}mg."
                )
            else:
                dose_mg = None
                status = Status.FLAG
                reasons.append(
                    f"Dose stated as a daily total (~{raw_daily_mg:.0f}mg/day) but the dosing "
                    f"frequency could not be determined - cannot verify the per-dose amount is safe."
                )

        if dose_mg is not None and dose_mg > 1000:
            status, reasons = Status.FLAG, reasons + [
                f"Single adult dose of {dose_mg:.0f}mg exceeds the typical 1000mg ceiling - verify."
            ]

        if order.interval_low_hr is not None and order.interval_low_hr < band.min_interval_hr:
            status, reasons = Status.BLOCK, reasons + [
                f"Dosing interval of {order.interval_low_hr}hrly is below the "
                f"{band.min_interval_hr}hrly minimum for adults."
            ]

        fixed_interval = (
            order.interval_low_hr is not None
            and order.interval_low_hr == order.interval_high_hr
        )
        if dose_mg is not None and doses_per_day is not None and fixed_interval:
            daily_mg = dose_mg * doses_per_day
            if patient.weight_kg is not None and patient.weight_kg < 50:
                cap = band.max_mg_day_lt50kg
                weight_note = f" ({patient.weight_kg}kg, <50kg cap applies)"
            else:
                cap = band.max_mg_day_ge50kg
                weight_note = "" if patient.weight_kg else " (weight not provided - assuming >=50kg; verify)"
            if daily_mg > cap:
                status, reasons = Status.BLOCK, reasons + [
                    f"Implied daily total of {daily_mg:.0f}mg exceeds the {cap}mg/day adult cap{weight_note}."
                ]

    if status == Status.PASS:
        reasons.append(f"Dose and frequency within standard range for {band_name}.")

    return Decision(status=status, reasons=reasons, rule_source="; ".join(rule.sources),
                     drug="paracetamol", extracted=order, patient=patient)


def _check_ibuprofen(order: ExtractedOrder, patient: PatientInfo) -> Decision:
    reasons: list[str] = []
    status = Status.PASS
    rule = IBUPROFEN

    if order.is_fuzzy_match:
        reasons.append(
            f"Drug name '{order.drug_name_raw}' did not exactly match a known alias - "
            f"matched via typo-tolerance to 'ibuprofen'. Verify this is correct."
        )
    if order.dose_is_range:
        reasons.append(
            f"Dose stated as a range ({order.dose_range_low:.0f}-{order.dose_value:.0f}{order.dose_unit}) - "
            f"checked against the upper bound ({order.dose_value:.0f}{order.dose_unit})."
        )

    validation_error = _validate_patient(patient)
    if validation_error:
        return Decision(
            status=Status.FLAG,
            reasons=reasons + [validation_error],
            drug="ibuprofen", extracted=order, patient=patient,
        )

    # Age checks run BEFORE the dose-presence check, deliberately: the
    # under-3-months concern is about the AGE itself, independent of what
    # dose was stated - found by independent evaluation that an order with
    # no parseable dose for a very young infant was silently passing
    # because the old order checked dose-presence first and returned early.
    if patient.age_years is None:
        return Decision(
            status=Status.FLAG,
            reasons=reasons + ["Patient age not provided - cannot select the correct dosing band."],
            drug="ibuprofen", extracted=order, patient=patient,
        )

    if patient.age_years < rule.min_age_years:
        return Decision(
            status=Status.FLAG,
            reasons=reasons + [
                "Patient is under 3 months - ibuprofen is generally avoided in this age group "
                "without specific clinician review, rather than dosed independently."
            ],
            drug="ibuprofen", extracted=order, patient=patient,
        )

    if order.dose_value is None:
        return Decision(
            status=Status.PASS,
            reasons=reasons + ["Drug mentioned with no dose stated - nothing to check."],
            drug="ibuprofen", extracted=order, patient=patient,
        )

    dose_mg = _dose_in_mg(order)
    doses_per_day = _doses_per_day(order)

    if patient.age_years < PAEDIATRIC_MAX_AGE_YEARS:
        band = rule.paediatric
        band_name = "paediatric (3mo-18yr)"

        if patient.weight_kg is None:
            return Decision(
                status=Status.FLAG,
                reasons=reasons + [f"Patient weight not provided - required for {band_name} weight-based dosing."],
                drug="ibuprofen", extracted=order, patient=patient,
            )

        if order.dose_unit == "mg/kg":
            if order.dose_is_daily_total:
                raw_daily_mg = order.dose_value * patient.weight_kg
                if doses_per_day:
                    dose_mg = raw_daily_mg / doses_per_day
                    per_dose_rate = dose_mg / patient.weight_kg
                    reasons.append(
                        f"Dose interpreted as a daily total ({order.dose_value:.0f}mg/kg/day) - "
                        f"per-dose equivalent is ~{per_dose_rate:.1f}mg/kg."
                    )
                    if per_dose_rate > band.mg_per_kg_dose_high * 1.1:
                        status = Status.FLAG
                        reasons.append(
                            f"Per-dose equivalent ({per_dose_rate:.1f}mg/kg) exceeds the standard "
                            f"{band.mg_per_kg_dose_low}-{band.mg_per_kg_dose_high}mg/kg/dose range for {band_name}."
                        )
                else:
                    dose_mg = None
                    status = Status.FLAG
                    reasons.append(
                        f"Dose stated as a daily total ({order.dose_value:.0f}mg/kg/day) but the "
                        f"dosing frequency could not be determined - cannot verify the per-dose "
                        f"amount is safe."
                    )
            else:
                # standard dosing is a RANGE (5-10mg/kg) - only the rate ABOVE
                # the top of that range is worth flagging, per the plan's own
                # "do NOT flag: standard peds 5-10mg/kg" rule
                if order.dose_value > band.mg_per_kg_dose_high * 1.1:
                    status = Status.FLAG
                    reasons.append(
                        f"Dose of {order.dose_value}mg/kg exceeds the standard "
                        f"{band.mg_per_kg_dose_low}-{band.mg_per_kg_dose_high}mg/kg/dose range for {band_name}."
                    )
                dose_mg = order.dose_value * patient.weight_kg
        elif dose_mg is not None:
            if order.dose_is_daily_total:
                raw_daily_mg = dose_mg
                if doses_per_day:
                    dose_mg = raw_daily_mg / doses_per_day
                    reasons.append(
                        f"Dose interpreted as a daily total (~{raw_daily_mg:.0f}mg/day) - "
                        f"per-dose equivalent calculated as ~{dose_mg:.0f}mg."
                    )
                else:
                    dose_mg = None
                    status = Status.FLAG
                    reasons.append(
                        f"Dose stated as a daily total (~{raw_daily_mg:.0f}mg/day) but the dosing "
                        f"frequency could not be determined - cannot verify the per-dose amount is safe."
                    )
            if dose_mg is not None:
                expected_high_mg = band.mg_per_kg_dose_high * patient.weight_kg
                cap = band.dose_cap_mg
                if dose_mg > cap:
                    status = Status.BLOCK
                    reasons.append(
                        f"Single dose of {dose_mg:.0f}mg exceeds the {cap}mg hard "
                        f"per-dose cap for {band_name}."
                    )
                elif dose_mg > expected_high_mg * 1.15:
                    status = Status.FLAG
                    reasons.append(
                        f"Single dose of {dose_mg:.0f}mg exceeds the weight-based calculation "
                        f"(up to {band.mg_per_kg_dose_high}mg/kg x {patient.weight_kg}kg = "
                        f"{expected_high_mg:.0f}mg) for this patient."
                    )

        if order.interval_low_hr is not None and order.interval_low_hr < band.min_interval_hr:
            status = Status.BLOCK
            reasons.append(
                f"Dosing interval of {order.interval_low_hr}hrly is below the "
                f"{band.min_interval_hr}hrly minimum for {band_name}."
            )

        fixed_interval = (
            order.interval_low_hr is not None and order.interval_low_hr == order.interval_high_hr
        )
        if dose_mg is not None and doses_per_day is not None and fixed_interval:
            daily_mg = dose_mg * doses_per_day
            # "whichever is lower" of the per-kg cap or the absolute cap
            effective_cap = min(band.max_mg_per_kg_day * patient.weight_kg, band.max_mg_day_absolute)
            if daily_mg > effective_cap:
                status = Status.BLOCK
                reasons.append(
                    f"Implied daily total of {daily_mg:.0f}mg exceeds the effective ceiling of "
                    f"{effective_cap:.0f}mg/day for {band_name} "
                    f"(lower of {band.max_mg_per_kg_day}mg/kg/day or {band.max_mg_day_absolute}mg/day)."
                )

    else:
        band = rule.adult
        band_name = "adult"

        if dose_mg is not None and order.dose_is_daily_total:
            raw_daily_mg = dose_mg
            if doses_per_day:
                dose_mg = raw_daily_mg / doses_per_day
                reasons.append(
                    f"Dose interpreted as a daily total (~{raw_daily_mg:.0f}mg/day) - "
                    f"per-dose equivalent calculated as ~{dose_mg:.0f}mg."
                )
            else:
                dose_mg = None
                status = Status.FLAG
                reasons.append(
                    f"Dose stated as a daily total (~{raw_daily_mg:.0f}mg/day) but the dosing "
                    f"frequency could not be determined - cannot verify the per-dose amount is safe."
                )

        if dose_mg is not None and dose_mg > 400:
            status = Status.FLAG
            reasons.append(f"Single adult dose of {dose_mg:.0f}mg exceeds the typical 400mg ceiling - verify.")

        if order.interval_low_hr is not None and order.interval_low_hr < band.min_interval_hr:
            status = Status.BLOCK
            reasons.append(
                f"Dosing interval of {order.interval_low_hr}hrly is below the "
                f"{band.min_interval_hr}hrly minimum for adults."
            )

        fixed_interval = (
            order.interval_low_hr is not None and order.interval_low_hr == order.interval_high_hr
        )
        if dose_mg is not None and doses_per_day is not None and fixed_interval:
            daily_mg = dose_mg * doses_per_day
            if daily_mg > band.max_mg_day_prescription:
                status = Status.BLOCK
                reasons.append(
                    f"Implied daily total of {daily_mg:.0f}mg exceeds even the "
                    f"{band.max_mg_day_prescription}mg/day prescription-strength ceiling."
                )
            elif daily_mg > band.max_mg_day_otc:
                if status != Status.BLOCK:
                    status = Status.FLAG
                reasons.append(
                    f"Implied daily total of {daily_mg:.0f}mg exceeds the {band.max_mg_day_otc}mg/day "
                    f"OTC ceiling - verify if a prescription-strength regimen is intended."
                )

    if status == Status.PASS:
        reasons.append(f"Dose and frequency within standard range for {band_name}.")

    return Decision(status=status, reasons=reasons, rule_source="; ".join(rule.sources),
                     drug="ibuprofen", extracted=order, patient=patient)


def _check_amoxicillin(order: ExtractedOrder, patient: PatientInfo) -> Decision:
    """Deliberately different shape from paracetamol/ibuprofen: amoxicillin
    has no single standard mg/kg/dose target (correct dose depends on what's
    being treated, not just weight), so there is no per-dose-rate check
    here. Safety is checked via the daily total and an absolute per-dose
    cap instead - see rulebook.py for the reasoning."""
    reasons: list[str] = []
    status = Status.PASS
    rule = AMOXICILLIN

    if order.is_fuzzy_match:
        reasons.append(
            f"Drug name '{order.drug_name_raw}' did not exactly match a known alias - "
            f"matched via typo-tolerance to 'amoxicillin'. Verify this is correct."
        )
    if order.dose_is_range:
        reasons.append(
            f"Dose stated as a range ({order.dose_range_low:.0f}-{order.dose_value:.0f}{order.dose_unit}) - "
            f"checked against the upper bound ({order.dose_value:.0f}{order.dose_unit})."
        )

    validation_error = _validate_patient(patient)
    if validation_error:
        return Decision(
            status=Status.FLAG,
            reasons=reasons + [validation_error],
            drug="amoxicillin", extracted=order, patient=patient,
        )

    if order.dose_value is None:
        return Decision(
            status=Status.PASS,
            reasons=reasons + ["Drug mentioned with no dose stated - nothing to check."],
            drug="amoxicillin", extracted=order, patient=patient,
        )

    if patient.age_years is None:
        return Decision(
            status=Status.FLAG,
            reasons=reasons + ["Patient age not provided - cannot select the correct dosing band."],
            drug="amoxicillin", extracted=order, patient=patient,
        )

    dose_mg = _dose_in_mg(order)
    doses_per_day = _doses_per_day(order)

    if order.dose_unit == "mg/kg" and patient.weight_kg is not None:
        dose_mg = order.dose_value * patient.weight_kg

    if dose_mg is not None and order.dose_is_daily_total:
        raw_daily_mg = dose_mg
        if doses_per_day:
            dose_mg = raw_daily_mg / doses_per_day
            reasons.append(
                f"Dose interpreted as a daily total (~{raw_daily_mg:.0f}mg/day) - "
                f"per-dose equivalent calculated as ~{dose_mg:.0f}mg."
            )
        else:
            dose_mg = None
            status = Status.FLAG
            reasons.append(
                f"Dose stated as a daily total (~{raw_daily_mg:.0f}mg/day) but the dosing "
                f"frequency could not be determined - cannot verify the per-dose amount is safe."
            )

    if patient.age_years < (3 / 12):
        band = rule.infant_under_3mo
        band_name = "infant under 3 months (reduced ceiling, not avoided)"

        if patient.weight_kg is None:
            return Decision(
                status=Status.FLAG,
                reasons=reasons + [f"Patient weight not provided - required for {band_name} weight-based dosing."],
                drug="amoxicillin", extracted=order, patient=patient,
            )

        if order.interval_low_hr is not None and order.interval_low_hr < band.min_interval_hr:
            status = Status.BLOCK
            reasons.append(
                f"Dosing interval of {order.interval_low_hr}hrly is below the {band.min_interval_hr}hrly "
                f"minimum for {band_name}."
            )

        fixed_interval = (
            order.interval_low_hr is not None and order.interval_low_hr == order.interval_high_hr
        )
        if dose_mg is not None and doses_per_day is not None and fixed_interval:
            daily_mg_per_kg = (dose_mg * doses_per_day) / patient.weight_kg
            if daily_mg_per_kg > band.max_mg_per_kg_day:
                status = Status.BLOCK
                reasons.append(
                    f"Implied daily total (~{daily_mg_per_kg:.0f}mg/kg/day) exceeds the reduced "
                    f"{band.max_mg_per_kg_day}mg/kg/day ceiling for {band_name}."
                )

    elif patient.age_years < PAEDIATRIC_MAX_AGE_YEARS:
        band = rule.paediatric
        band_name = "paediatric (3mo-18yr)"

        if patient.weight_kg is None:
            return Decision(
                status=Status.FLAG,
                reasons=reasons + [f"Patient weight not provided - required for {band_name} weight-based dosing."],
                drug="amoxicillin", extracted=order, patient=patient,
            )

        if dose_mg is not None and dose_mg > band.dose_cap_mg:
            status = Status.BLOCK
            reasons.append(
                f"Single dose of {dose_mg:.0f}mg exceeds the {band.dose_cap_mg}mg absolute per-dose "
                f"cap for {band_name} (applies even in high-dose regimens)."
            )

        if order.interval_low_hr is not None and order.interval_low_hr < band.min_interval_hr:
            status = Status.BLOCK
            reasons.append(
                f"Dosing interval of {order.interval_low_hr}hrly is below the "
                f"{band.min_interval_hr}hrly minimum for {band_name}."
            )

        fixed_interval = (
            order.interval_low_hr is not None and order.interval_low_hr == order.interval_high_hr
        )
        if dose_mg is not None and doses_per_day is not None and fixed_interval:
            daily_mg = dose_mg * doses_per_day
            daily_mg_per_kg = daily_mg / patient.weight_kg
            if daily_mg > band.max_mg_day_absolute or daily_mg_per_kg > band.verify_mg_per_kg_day:
                status = Status.BLOCK
                reasons.append(
                    f"Implied daily total (~{daily_mg:.0f}mg, ~{daily_mg_per_kg:.0f}mg/kg/day) exceeds "
                    f"the {band.max_mg_day_absolute}mg/day absolute cap or the "
                    f"{band.verify_mg_per_kg_day}mg/kg/day outlier threshold for {band_name}."
                )
            elif daily_mg_per_kg > band.max_mg_per_kg_day:
                if status != Status.BLOCK:
                    status = Status.FLAG
                reasons.append(
                    f"Implied daily total (~{daily_mg_per_kg:.0f}mg/kg/day) is above the standard "
                    f"high-dose ceiling of {band.max_mg_per_kg_day}mg/kg/day - verify indication "
                    f"(this can be legitimate for e.g. resistant otitis media, but worth confirming)."
                )

    else:
        band = rule.adult
        band_name = "adult"

        # These didn't exist before - found via independent evaluation that
        # an unusually large single adult dose went completely unflagged as
        # long as the daily total (if computable at all) stayed under the
        # 4000mg absolute cap. Checked independent of frequency info
        # specifically so a single large stat dose with no interval stated
        # is still caught.
        if dose_mg is not None and dose_mg > band.absolute_max_dose_mg:
            status = Status.BLOCK
            reasons.append(
                f"Single dose of {dose_mg:.0f}mg exceeds the {band.absolute_max_dose_mg}mg absolute "
                f"per-dose ceiling for adults, regardless of frequency."
            )
        elif dose_mg is not None and dose_mg > band.typical_max_dose_mg:
            status = Status.FLAG
            reasons.append(
                f"Single dose of {dose_mg:.0f}mg is above the typical {band.typical_max_dose_mg}mg "
                f"single-dose figure for adults - verify context (large one-off doses can be "
                f"legitimate, e.g. certain prophylaxis regimens, but are uncommon)."
            )

        if order.interval_low_hr is not None and order.interval_low_hr < band.min_interval_hr:
            status = Status.BLOCK
            reasons.append(
                f"Dosing interval of {order.interval_low_hr}hrly is below the "
                f"{band.min_interval_hr}hrly minimum for adults."
            )

        fixed_interval = (
            order.interval_low_hr is not None and order.interval_low_hr == order.interval_high_hr
        )
        if dose_mg is not None and doses_per_day is not None and fixed_interval:
            daily_mg = dose_mg * doses_per_day
            if daily_mg > band.max_mg_day_absolute:
                status = Status.BLOCK
                reasons.append(
                    f"Implied daily total of {daily_mg:.0f}mg exceeds the {band.max_mg_day_absolute}mg/day "
                    f"absolute adult ceiling."
                )

    if status == Status.PASS:
        reasons.append(f"Dose and frequency within the wide standard range for {band_name}.")

    return Decision(status=status, reasons=reasons, rule_source="; ".join(rule.sources),
                     drug="amoxicillin", extracted=order, patient=patient)


def _check_loratadine(order: ExtractedOrder, patient: PatientInfo) -> Decision:
    """A fourth pattern: age-banded with FIXED doses, not weight-based at
    all - loratadine is explicitly dosed by age in the source material."""
    reasons: list[str] = []
    status = Status.PASS
    rule = LORATADINE

    if order.is_fuzzy_match:
        reasons.append(
            f"Drug name '{order.drug_name_raw}' did not exactly match a known alias - "
            f"matched via typo-tolerance to 'loratadine'. Verify this is correct."
        )
    if order.dose_is_range:
        reasons.append(
            f"Dose stated as a range ({order.dose_range_low:.0f}-{order.dose_value:.0f}{order.dose_unit}) - "
            f"checked against the upper bound ({order.dose_value:.0f}{order.dose_unit})."
        )

    validation_error = _validate_patient(patient)
    if validation_error:
        return Decision(status=Status.FLAG, reasons=reasons + [validation_error],
                         drug="loratadine", extracted=order, patient=patient)

    if order.dose_value is None:
        return Decision(
            status=Status.PASS,
            reasons=reasons + ["Drug mentioned with no dose stated - nothing to check."],
            drug="loratadine", extracted=order, patient=patient,
        )

    if patient.age_years is None:
        return Decision(
            status=Status.FLAG,
            reasons=reasons + [
                "Patient age not provided - loratadine is dosed by age, not weight, "
                "so age is required to select the correct band."
            ],
            drug="loratadine", extracted=order, patient=patient,
        )

    if patient.age_years < rule.min_age_years:
        return Decision(
            status=Status.FLAG,
            reasons=reasons + [
                f"Patient is under {rule.min_age_years:.0f} years - loratadine dosing is not "
                f"established for this age without specific clinician guidance."
            ],
            drug="loratadine", extracted=order, patient=patient,
        )

    dose_mg = _dose_in_mg(order)
    if dose_mg is None:
        return Decision(
            status=Status.FLAG,
            reasons=reasons + [
                "Dose unit not recognized for loratadine - expected a plain mg amount "
                "(loratadine is never dosed as mg/kg)."
            ],
            drug="loratadine", extracted=order, patient=patient,
        )

    if patient.age_years < rule.young_band_max_age_years:
        expected_mg = rule.young_band_dose_mg
        band_name = f"young child ({rule.min_age_years:.0f}-<{rule.young_band_max_age_years:.0f}yr)"
    else:
        expected_mg = rule.standard_dose_mg
        band_name = f"{rule.young_band_max_age_years:.0f}yr+ / adult"

    if dose_mg > rule.max_mg_day:
        status = Status.BLOCK
        reasons.append(
            f"Single dose of {dose_mg:.0f}mg exceeds the {rule.max_mg_day:.0f}mg/day "
            f"absolute ceiling for {band_name}."
        )
    elif dose_mg > expected_mg:
        status = Status.FLAG
        reasons.append(
            f"Dose of {dose_mg:.0f}mg exceeds the standard {expected_mg:.0f}mg dose for {band_name}."
        )

    fixed_interval = order.interval_low_hr is not None and order.interval_low_hr == order.interval_high_hr
    if fixed_interval and order.interval_low_hr < rule.min_interval_hr:
        status = Status.BLOCK
        reasons.append(
            f"Dosing interval of {order.interval_low_hr}hrly is below the {rule.min_interval_hr:.0f}hrly "
            f"minimum - loratadine is once-daily only."
        )

    if status == Status.PASS:
        reasons.append(f"Dose within standard range for {band_name}.")

    return Decision(status=status, reasons=reasons, rule_source="; ".join(rule.sources),
                     drug="loratadine", extracted=order, patient=patient)


def _check_dexamethasone(order: ExtractedOrder, patient: PatientInfo) -> Decision:
    """Same wide-band, absolute-cap pattern as amoxicillin - dexamethasone
    is even more indication-variable than amoxicillin (legitimate croup
    dosing alone spans a 4x range depending on protocol)."""
    reasons: list[str] = []
    status = Status.PASS
    rule = DEXAMETHASONE

    if order.is_fuzzy_match:
        reasons.append(
            f"Drug name '{order.drug_name_raw}' did not exactly match a known alias - "
            f"matched via typo-tolerance to 'dexamethasone'. Verify this is correct."
        )
    if order.dose_is_range:
        reasons.append(
            f"Dose stated as a range ({order.dose_range_low:.0f}-{order.dose_value:.0f}{order.dose_unit}) - "
            f"checked against the upper bound ({order.dose_value:.0f}{order.dose_unit})."
        )

    validation_error = _validate_patient(patient)
    if validation_error:
        return Decision(status=Status.FLAG, reasons=reasons + [validation_error],
                         drug="dexamethasone", extracted=order, patient=patient)

    if order.dose_value is None:
        return Decision(
            status=Status.PASS,
            reasons=reasons + ["Drug mentioned with no dose stated - nothing to check."],
            drug="dexamethasone", extracted=order, patient=patient,
        )

    if patient.age_years is None:
        return Decision(
            status=Status.FLAG,
            reasons=reasons + ["Patient age not provided - cannot select the correct dosing band."],
            drug="dexamethasone", extracted=order, patient=patient,
        )

    dose_mg = _dose_in_mg(order)
    doses_per_day = _doses_per_day(order)

    if order.dose_unit == "mg/kg" and patient.weight_kg is not None:
        dose_mg = order.dose_value * patient.weight_kg

    if dose_mg is not None and order.dose_is_daily_total:
        raw_daily_mg = dose_mg
        if doses_per_day:
            dose_mg = raw_daily_mg / doses_per_day
            reasons.append(
                f"Dose interpreted as a daily total (~{raw_daily_mg:.0f}mg/day) - "
                f"per-dose equivalent calculated as ~{dose_mg:.0f}mg."
            )
        else:
            dose_mg = None
            status = Status.FLAG
            reasons.append(
                f"Dose stated as a daily total (~{raw_daily_mg:.0f}mg/day) but the dosing "
                f"frequency could not be determined - cannot verify the per-dose amount is safe."
            )

    if patient.age_years < PAEDIATRIC_MAX_AGE_YEARS:
        band = rule.paediatric
        band_name = "paediatric"

        if patient.weight_kg is None:
            return Decision(
                status=Status.FLAG,
                reasons=reasons + [f"Patient weight not provided - required for {band_name} weight-based dosing."],
                drug="dexamethasone", extracted=order, patient=patient,
            )

        if dose_mg is not None:
            if dose_mg > band.dose_cap_mg:
                status = Status.BLOCK
                reasons.append(
                    f"Single dose of {dose_mg:.1f}mg exceeds the {band.dose_cap_mg:.0f}mg "
                    f"absolute per-dose cap for {band_name}."
                )
            else:
                rate = dose_mg / patient.weight_kg
                if rate > band.block_mg_per_kg:
                    status = Status.BLOCK
                    reasons.append(
                        f"Dose rate (~{rate:.2f}mg/kg) exceeds even the outlier threshold of "
                        f"{band.block_mg_per_kg}mg/kg for {band_name}."
                    )
                elif rate > band.verify_mg_per_kg:
                    status = Status.FLAG
                    reasons.append(
                        f"Dose rate (~{rate:.2f}mg/kg) is above the standard "
                        f"{band.mg_per_kg_dose_low}-{band.mg_per_kg_dose_high}mg/kg range for "
                        f"{band_name} - verify indication (some indications legitimately use "
                        f"higher doses, but worth confirming)."
                    )

        if order.interval_low_hr is not None and order.interval_low_hr < band.min_interval_hr:
            status = Status.BLOCK
            reasons.append(
                f"Dosing interval of {order.interval_low_hr}hrly is below the "
                f"{band.min_interval_hr}hrly minimum for {band_name}."
            )

    else:
        band = rule.adult
        band_name = "adult"

        if dose_mg is not None:
            if dose_mg > band.block_above_mg:
                status = Status.BLOCK
                reasons.append(
                    f"Single adult dose of {dose_mg:.0f}mg exceeds {band.block_above_mg:.0f}mg - "
                    f"well outside typical range."
                )
            elif dose_mg > band.verify_above_mg:
                status = Status.FLAG
                reasons.append(
                    f"Single adult dose of {dose_mg:.0f}mg is above the typical "
                    f"{band.typical_range_mg[0]:.0f}-{band.typical_range_mg[1]:.0f}mg range - "
                    f"verify indication."
                )

        if order.interval_low_hr is not None and order.interval_low_hr < band.min_interval_hr:
            status = Status.BLOCK
            reasons.append(
                f"Dosing interval of {order.interval_low_hr}hrly is below the "
                f"{band.min_interval_hr}hrly minimum for adults."
            )

    if status == Status.PASS:
        reasons.append(f"Dose and frequency within the wide standard range for {band_name}.")

    return Decision(status=status, reasons=reasons, rule_source="; ".join(rule.sources),
                     drug="dexamethasone", extracted=order, patient=patient)


def _check_fentanyl(order: ExtractedOrder, patient: PatientInfo) -> Decision:
    """OPIOID - deliberately more conservative than every other drug here.
    See the FENTANYL rule's comment block in rulebook.py for the full
    reasoning. Every decision this returns - including PASS - carries the
    mandatory disclaimer about tolerance/interaction factors this tool
    cannot assess. Scoped to paediatric INTRANASAL use only."""
    reasons: list[str] = []
    status = Status.PASS
    rule = FENTANYL
    band = rule.paediatric_intranasal

    if order.is_fuzzy_match:
        reasons.append(
            f"Drug name '{order.drug_name_raw}' did not exactly match a known alias - "
            f"matched via typo-tolerance to 'fentanyl'. Verify this is correct."
        )
    if order.dose_is_range:
        reasons.append(
            f"Dose stated as a range ({order.dose_range_low}-{order.dose_value}{order.dose_unit}) - "
            f"checked against the upper bound ({order.dose_value}{order.dose_unit})."
        )

    # Always present, regardless of outcome - a clean PASS here must never
    # look like "opioid safety fully verified."
    reasons.append(rule.mandatory_disclaimer)

    if order.route and order.route != "IN":
        return Decision(
            status=Status.FLAG,
            reasons=reasons + [
                f"Route '{order.route}' stated - this rulebook only covers intranasal fentanyl "
                f"dosing, which uses a different pattern from {order.route} administration. Not verified."
            ],
            drug="fentanyl", extracted=order, patient=patient,
        )

    validation_error = _validate_patient(patient)
    if validation_error:
        return Decision(status=Status.FLAG, reasons=reasons + [validation_error],
                         drug="fentanyl", extracted=order, patient=patient)

    if order.dose_value is None:
        return Decision(
            status=Status.PASS,
            reasons=reasons + ["Drug mentioned with no dose stated - nothing to check."],
            drug="fentanyl", extracted=order, patient=patient,
        )

    if patient.age_years is None:
        return Decision(
            status=Status.FLAG,
            reasons=reasons + ["Patient age not provided - cannot select the correct dosing band."],
            drug="fentanyl", extracted=order, patient=patient,
        )

    if patient.age_years < band.min_age_years:
        status = Status.FLAG
        reasons.append(
            f"Patient is under {band.min_age_years:.0f} year - the evidence base for intranasal "
            f"fentanyl dosing is limited in this age group; verify with a senior clinician "
            f"regardless of the dose itself."
        )

    if patient.weight_kg is None:
        return Decision(
            status=Status.FLAG,
            reasons=reasons + ["Patient weight not provided - required for weight-based opioid dosing."],
            drug="fentanyl", extracted=order, patient=patient,
        )

    # Critical unit-safety check: fentanyl is dosed in MICROGRAMS, a
    # thousand-fold smaller unit than milligrams. A mg/mcg mix-up for this
    # specific drug is a well-documented, real category of fatal dosing
    # error - caught and blocked explicitly, not silently computed.
    dose_mcg = None
    rate = None
    if order.dose_unit in ("mg/kg", "mg"):
        status = Status.BLOCK
        wrong_unit_dose = f"{order.dose_value}{order.dose_unit}"
        reasons.append(
            f"Dose stated as {wrong_unit_dose} - fentanyl is dosed in MICROGRAMS (mcg), not "
            f"milligrams (mg). If {order.dose_value}mcg{'/kg' if 'kg' in order.dose_unit else ''} "
            f"was intended, verify the unit was written correctly - as literally stated, this "
            f"would be a massive, likely fatal overdose."
        )
        return Decision(status=status, reasons=reasons, rule_source="; ".join(rule.sources),
                         drug="fentanyl", extracted=order, patient=patient)
    elif order.dose_unit == "mcg/kg":
        dose_mcg = order.dose_value * patient.weight_kg
        rate = order.dose_value
    elif order.dose_unit == "mcg":
        dose_mcg = order.dose_value
        rate = dose_mcg / patient.weight_kg

    if dose_mcg is not None:
        if dose_mcg > band.dose_cap_mcg:
            status = Status.BLOCK
            reasons.append(
                f"Single dose of {dose_mcg:.0f}mcg exceeds the {band.dose_cap_mcg:.0f}mcg "
                f"standard opioid-naive ceiling."
            )
        elif rate is not None and rate > band.verify_mcg_per_kg:
            if status != Status.BLOCK:
                status = Status.FLAG
            reasons.append(
                f"Dose rate (~{rate:.2f}mcg/kg) is above the standard "
                f"{band.typical_range_low:.1f}-{band.typical_range_high:.1f}mcg/kg range - doses "
                f"at this level have been used safely in monitored research settings, but verify "
                f"intent and ensure appropriate monitoring here."
            )

    if patient.opioid_tolerant is True:
        if status == Status.PASS:
            status = Status.FLAG
        reasons.append(
            "Patient marked as opioid-tolerant - the naive-patient ceilings above may not apply. "
            "Verify against a tolerance-adjusted protocol independently; this tool does not encode "
            "tolerant-patient dosing."
        )

    if order.interval_low_hr is not None:
        redose_hr = band.min_redose_interval_min / 60
        if order.interval_low_hr < redose_hr:
            status = Status.BLOCK
            reasons.append(
                f"Redosing interval of {order.interval_low_hr}hrly is below the "
                f"{band.min_redose_interval_min:.0f}-minute minimum between doses."
            )

    if status == Status.PASS:
        reasons.append(
            f"Dose within the standard {band.typical_range_low:.1f}-{band.typical_range_high:.1f}mcg/kg "
            f"range for paediatric intranasal use."
        )

    return Decision(status=status, reasons=reasons, rule_source="; ".join(rule.sources),
                     drug="fentanyl", extracted=order, patient=patient)


def _check_oxycodone(order: ExtractedOrder, patient: PatientInfo) -> Decision:
    """OPIOID - same conservative philosophy as fentanyl above. Scoped to
    IMMEDIATE-RELEASE, opioid-naive initiation dosing only - extended-
    release and tolerant-patient dosing are explicitly out of scope."""
    reasons: list[str] = []
    status = Status.PASS
    rule = OXYCODONE

    if order.is_fuzzy_match:
        reasons.append(
            f"Drug name '{order.drug_name_raw}' did not exactly match a known alias - "
            f"matched via typo-tolerance to 'oxycodone'. Verify this is correct."
        )
    if order.dose_is_range:
        reasons.append(
            f"Dose stated as a range ({order.dose_range_low}-{order.dose_value}{order.dose_unit}) - "
            f"checked against the upper bound ({order.dose_value}{order.dose_unit})."
        )

    reasons.append(rule.mandatory_disclaimer)

    validation_error = _validate_patient(patient)
    if validation_error:
        return Decision(status=Status.FLAG, reasons=reasons + [validation_error],
                         drug="oxycodone", extracted=order, patient=patient)

    if order.dose_value is None:
        return Decision(
            status=Status.PASS,
            reasons=reasons + ["Drug mentioned with no dose stated - nothing to check."],
            drug="oxycodone", extracted=order, patient=patient,
        )

    if patient.age_years is None:
        return Decision(
            status=Status.FLAG,
            reasons=reasons + ["Patient age not provided - cannot select the correct dosing band."],
            drug="oxycodone", extracted=order, patient=patient,
        )

    dose_mg = _dose_in_mg(order)
    doses_per_day = _doses_per_day(order)

    if order.dose_unit == "mg/kg" and patient.weight_kg is not None:
        dose_mg = order.dose_value * patient.weight_kg

    if dose_mg is not None and order.dose_is_daily_total:
        raw_daily_mg = dose_mg
        if doses_per_day:
            dose_mg = raw_daily_mg / doses_per_day
            reasons.append(
                f"Dose interpreted as a daily total (~{raw_daily_mg:.1f}mg/day) - "
                f"per-dose equivalent calculated as ~{dose_mg:.1f}mg."
            )
        else:
            dose_mg = None
            status = Status.FLAG
            reasons.append(
                "Dose stated as a daily total but the dosing frequency could not be "
                "determined - cannot verify the per-dose amount is safe."
            )

    if patient.opioid_tolerant is True:
        if status == Status.PASS:
            status = Status.FLAG
        reasons.append(
            "Patient marked as opioid-tolerant - the naive-patient ceilings below may not "
            "apply. Verify against a tolerance-adjusted protocol independently."
        )

    if patient.age_years < 0.5:
        band = rule.infant_under_6mo
        band_name = "infant under 6 months"

        if patient.weight_kg is None:
            return Decision(
                status=Status.FLAG,
                reasons=reasons + [f"Patient weight not provided - required for {band_name} weight-based dosing."],
                drug="oxycodone", extracted=order, patient=patient,
            )

        if order.dose_unit == "mg/kg":
            if order.dose_value > band.block_mg_per_kg:
                status = Status.BLOCK
                reasons.append(
                    f"Dose of {order.dose_value}mg/kg is {order.dose_value / band.mg_per_kg_dose:.1f}x "
                    f"the reduced {band.mg_per_kg_dose}mg/kg standard for {band_name} - well beyond a "
                    f"modest excess, for the most vulnerable population this rulebook covers."
                )
            elif order.dose_value > band.mg_per_kg_dose * 1.2:
                status = Status.FLAG
                reasons.append(
                    f"Dose of {order.dose_value}mg/kg exceeds the reduced "
                    f"{band.mg_per_kg_dose}mg/kg standard for {band_name}."
                )
            dose_mg = order.dose_value * patient.weight_kg

        if dose_mg is not None and dose_mg > band.dose_cap_mg:
            status = Status.BLOCK
            reasons.append(
                f"Single dose of {dose_mg:.2f}mg exceeds the {band.dose_cap_mg}mg cap for {band_name}."
            )

        if order.interval_low_hr is not None and order.interval_low_hr < band.min_interval_hr:
            status = Status.BLOCK
            reasons.append(
                f"Dosing interval of {order.interval_low_hr}hrly is below the "
                f"{band.min_interval_hr}hrly minimum for {band_name}."
            )

    elif patient.age_years < PAEDIATRIC_MAX_AGE_YEARS:
        band = rule.paediatric
        band_name = "paediatric, opioid-naive"

        if patient.weight_kg is None:
            return Decision(
                status=Status.FLAG,
                reasons=reasons + [f"Patient weight not provided - required for {band_name} weight-based dosing."],
                drug="oxycodone", extracted=order, patient=patient,
            )

        if order.dose_unit == "mg/kg":
            if order.dose_value > band.mg_per_kg_dose_high * 1.1:
                status = Status.FLAG
                reasons.append(
                    f"Dose of {order.dose_value}mg/kg exceeds the standard "
                    f"{band.mg_per_kg_dose_low}-{band.mg_per_kg_dose_high}mg/kg/dose range for {band_name}."
                )
            dose_mg = order.dose_value * patient.weight_kg
        elif dose_mg is not None:
            expected_high = band.mg_per_kg_dose_high * patient.weight_kg
            if dose_mg > expected_high * 1.15:
                status = Status.FLAG
                reasons.append(
                    f"Single dose of {dose_mg:.1f}mg exceeds the weight-based calculation "
                    f"(up to {band.mg_per_kg_dose_high}mg/kg x {patient.weight_kg}kg = "
                    f"{expected_high:.1f}mg) for {band_name}."
                )

        if dose_mg is not None and dose_mg > band.dose_cap_mg:
            status = Status.BLOCK
            reasons.append(
                f"Single dose of {dose_mg:.1f}mg exceeds the {band.dose_cap_mg}mg "
                f"opioid-naive per-dose cap for {band_name}."
            )

        if order.interval_low_hr is not None and order.interval_low_hr < band.min_interval_hr:
            status = Status.BLOCK
            reasons.append(
                f"Dosing interval of {order.interval_low_hr}hrly is below the "
                f"{band.min_interval_hr}hrly minimum for {band_name}."
            )

        fixed_interval = order.interval_low_hr is not None and order.interval_low_hr == order.interval_high_hr
        if dose_mg is not None and doses_per_day is not None and fixed_interval:
            daily_per_kg = (dose_mg * doses_per_day) / patient.weight_kg
            if daily_per_kg > band.max_mg_per_kg_day:
                status = Status.BLOCK
                reasons.append(
                    f"Implied daily total (~{daily_per_kg:.2f}mg/kg/day) exceeds the "
                    f"{band.max_mg_per_kg_day}mg/kg/day ceiling for {band_name}."
                )

    else:
        band = rule.adult
        band_name = "adult, opioid-naive initiation"

        if dose_mg is not None:
            if dose_mg > band.block_above_mg:
                status = Status.BLOCK
                reasons.append(
                    f"Single dose of {dose_mg:.0f}mg exceeds {band.block_above_mg:.0f}mg - "
                    f"well outside typical opioid-naive initiation range."
                )
            elif dose_mg > band.verify_above_mg:
                if status != Status.BLOCK:
                    status = Status.FLAG
                reasons.append(
                    f"Single dose of {dose_mg:.0f}mg is above the typical opioid-naive range "
                    f"({band.typical_range_mg[0]:.0f}-{band.typical_range_mg[1]:.0f}mg) - verify "
                    f"if the patient is actually opioid-tolerant."
                )

        if order.interval_low_hr is not None and order.interval_low_hr < band.min_interval_hr:
            status = Status.BLOCK
            reasons.append(
                f"Dosing interval of {order.interval_low_hr}hrly is below the "
                f"{band.min_interval_hr}hrly minimum for {band_name}."
            )

    if status == Status.PASS:
        reasons.append(f"Dose and frequency within standard opioid-naive range for {band_name}.")

    return Decision(status=status, reasons=reasons, rule_source="; ".join(rule.sources),
                     drug="oxycodone", extracted=order, patient=patient)


class DrugChecker(Protocol):
    """The contract every drug-check function must satisfy: takes the
    extracted order and patient, returns a Decision. This is what "adding
    a new drug" actually means in code terms - formalized here instead of
    left as an unenforced convention, so a type-checker (mypy/pyright) or
    a reviewer can verify the shape directly rather than trusting that
    copy-paste from an existing _check_<drug> function got everything
    right."""
    def __call__(self, order: ExtractedOrder, patient: PatientInfo) -> Decision: ...


# Explicit registry, not an if/elif chain. This matters for a reason beyond
# tidiness: with the old if/elif dispatch, a drug that normalize_drug()
# recognizes (has an RxCUI mapping) but whose elif branch was forgotten
# would silently produce ZERO decisions for that order - no FLAG, no
# error, nothing. A registry lookup makes that failure mode visible
# instead (see check_order below) - forgetting to register a checker now
# produces an explicit "this drug isn't verified yet" FLAG, not silence.
_CHECKERS: dict = {
    "paracetamol": _check_paracetamol,
    "ibuprofen": _check_ibuprofen,
    "amoxicillin": _check_amoxicillin,
    "loratadine": _check_loratadine,
    "dexamethasone": _check_dexamethasone,
    "fentanyl": _check_fentanyl,
    "oxycodone": _check_oxycodone,
}


def check_order(text: str, patient: PatientInfo) -> list[Decision]:
    """Main entry point. Returns one Decision per recognized drug order found
    in the text. Orders for drugs not yet in the rulebook are skipped, not
    flagged - v0 only checks what it has real rules for.

    CONTRACT: text must describe exactly ONE patient. This tool has no way
    to know which order belongs to which patient if a single call's text
    covers more than one (e.g. a multi-bed ward-round note) - it will apply
    the single `patient` argument to every order it finds, which will be
    wrong for any patient other than the one actually passed in. Callers
    are responsible for splitting multi-patient text before calling this -
    e.g. one call per bed/patient, not one call for a whole round."""
    decisions = []
    for order in extract_orders(text):
        normalized = normalize_drug(order.drug_canonical)
        if not normalized:
            continue  # not in the rulebook yet - out of scope for v0, not an error

        checker = _CHECKERS.get(normalized.canonical_name)
        if checker is None:
            # normalize_drug() recognizes this drug (it has an RxCUI
            # mapping) but no check function is registered for it yet -
            # surface this loudly rather than silently producing nothing.
            decisions.append(Decision(
                status=Status.FLAG,
                reasons=[
                    f"'{normalized.canonical_name}' is recognized but has no safety check "
                    f"implemented yet - this order was NOT verified against any rulebook."
                ],
                drug=normalized.canonical_name, extracted=order, patient=patient,
            ))
            continue

        decisions.append(checker(order, patient))

    return decisions


# ============================================================
# LOG
# ============================================================

import hashlib
import json
from datetime import datetime, timezone



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




# ============================================================
# ALL 111 TEST CASES ACROSS 7 DRUGS
# paracetamol(19) + ibuprofen(19) + amoxicillin(20) + loratadine(10) +
# dexamethasone(13) + fentanyl(15) + oxycodone(15)
# ============================================================

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


    # ---- normal / should PASS ----
    ("standard peds mg/kg within range (8mg/kg), PRN range interval",
     "ibuprofen 8mg/kg PO 6-8 hourly PRN",
     PatientInfo(age_years=5, weight_kg=20), Status.PASS),

    ("standard peds at low end of range (5mg/kg)",
     "ibuprofen 5mg/kg PO 6-8 hourly PRN",
     PatientInfo(age_years=4, weight_kg=16), Status.PASS),

    ("standard peds at top of range exactly (10mg/kg)",
     "ibuprofen 10mg/kg PO 6-8 hourly PRN",
     PatientInfo(age_years=5, weight_kg=20), Status.PASS),

    ("brand name alias resolves correctly (nurofen)",
     "nurofen 5mg/kg PO 6-8 hourly PRN",
     PatientInfo(age_years=4, weight_kg=16), Status.PASS),

    ("peds fixed mg dose within weight-based range",
     "ibuprofen 160mg PO 6-8 hourly PRN",
     PatientInfo(age_years=6, weight_kg=20), Status.PASS),

    ("adult standard 200mg 6hourly - 800mg/day, under OTC ceiling",
     "ibuprofen 200mg PO 6 hourly",
     PatientInfo(age_years=35, weight_kg=75), Status.PASS),

    ("adult 400mg TDS - exactly at 1200mg/day OTC ceiling, not over",
     "ibuprofen 400mg PO TDS",
     PatientInfo(age_years=40, weight_kg=80), Status.PASS),

    ("drug mentioned with no dose stated",
     "continue ibuprofen as charted, otherwise stable",
     PatientInfo(age_years=5, weight_kg=20), Status.PASS),

    # ---- dangerous / should FLAG or BLOCK ----
    ("peds single dose exceeds 400mg hard cap",
     "ibuprofen 500mg PO 6 hourly",
     PatientInfo(age_years=12, weight_kg=45), Status.BLOCK),

    ("peds dosing interval below 6hr minimum",
     "ibuprofen 8mg/kg PO 4 hourly",
     PatientInfo(age_years=8, weight_kg=25), Status.BLOCK),

    ("peds daily total exceeds effective per-kg ceiling (lower than absolute)",
     "ibuprofen 380mg PO 6 hourly",
     PatientInfo(age_years=13, weight_kg=35), Status.BLOCK),

    ("under 3 months - avoid without clinician review",
     "ibuprofen 5mg/kg PO 8 hourly PRN",
     PatientInfo(age_years=0.1, weight_kg=5), Status.FLAG),

    ("mg/kg rate above standard range, PRN interval so daily-total not computed",
     "ibuprofen 15mg/kg PO 6-8 hourly PRN",
     PatientInfo(age_years=5, weight_kg=20), Status.FLAG),

    ("adult single dose over 400mg, no frequency stated",
     "ibuprofen 600mg PO",
     PatientInfo(age_years=35, weight_kg=75), Status.FLAG),

    ("adult daily total exceeds OTC ceiling but not prescription ceiling",
     "ibuprofen 400mg PO 6 hourly",
     PatientInfo(age_years=35, weight_kg=75), Status.FLAG),

    ("adult daily total exceeds even prescription-strength ceiling",
     "ibuprofen 800mg PO 4 hourly",
     PatientInfo(age_years=35, weight_kg=75), Status.BLOCK),

    ("misspelled drug name, genuinely dangerous dose - must not go silent",
     "ibuprofn 500mg PO 6 hourly",
     PatientInfo(age_years=12, weight_kg=45), Status.BLOCK),

    # ---- missing-input handling ----
    ("patient age not provided",
     "ibuprofen 5mg/kg PO 6-8 hourly PRN",
     PatientInfo(weight_kg=20), Status.FLAG),

    ("patient weight not provided for a child",
     "ibuprofen 5mg/kg PO 6-8 hourly PRN",
     PatientInfo(age_years=5), Status.FLAG),


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
