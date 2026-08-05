"""
Rulebook: the actual clinical thresholds, as validated dataclasses.

Deliberately separated from engine.py so a clinician or risk board can read
the numbers here without reading control-flow code, and so updating a
threshold never means touching the checking logic.

v0.6: converted from plain dicts to dataclasses. The dicts worked and were
easy to read, but had a real weakness: a typo'd key (e.g. "max_mg_perkg_day"
instead of "max_mg_per_kg_day") wouldn't error - it would either raise a
KeyError deep inside engine.py, far from the actual mistake, or silently
vanish if the accessing code used .get() with a default. Dataclasses catch
this at the point of definition instead: a typo'd field name is a TypeError
the moment this module is imported, not a runtime surprise. Each drug's
bands are deliberately NOT forced into one shared shape - paracetamol,
ibuprofen, and amoxicillin have genuinely different band structures (a
design feature demonstrated across this whole build, not an oversight),
so each gets its own precise dataclass rather than a generic one padded
with optional fields nobody needs.

Sources: AMH Children's Dosing Companion, Therapeutic Guidelines/eTG,
Perth Children's Hospital public monographs. Figures reference-compiled,
not copied verbatim - verify against the live source before relying on
this in anything beyond a synthetic-data pilot.
"""

from dataclasses import dataclass

# ============================================================
# PARACETAMOL
# ============================================================

@dataclass(frozen=True)
class ParacetamolWeightBand:
    mg_per_kg_dose: float
    min_interval_hr: float
    max_interval_hr: float
    max_mg_per_kg_day: float
    dose_cap_mg: float | None = None
    # up to here is standard - flag as "verify", don't hard-block, since
    # short-term inpatient dosing legitimately runs higher than the
    # standard max_mg_per_kg_day
    verify_mg_per_kg_day: float | None = None


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
