# Dosage Safety Pilot — v0 Working Plan (consolidated)

## What this is
A rules-based software safety layer (not itself an AI model) that checks AI-generated
clinical text for dangerous drug-dosage errors before it reaches a human. Sits between
a healthcare AI product's output and the end user — does not diagnose, prescribe, or
touch the EHR.

## Naming (still under review — not finalized)
- "Bastion" ruled out: already used by two funded healthcare-AI companies
  (Bastion Health, Bastion Intelligence / BastionGPT) — trademark/confusion risk.
- Candidates still open: Warden, Custodian, Vigil, Magen (Hebrew for "shield") —
  check for Israeli health-tech naming collisions if going global.
- Next step: check ASIC business name register + domain + GitHub/PyPI package
  name availability before committing.

## What it is NOT (scope discipline — Layer 1 vs Layer 2)
- Not a certification body (that's the CHAI-style "big game" — years away, if ever)
- Not hospital-protocol-adaptive yet (Layer 2 — needs a real hospital
  relationship to get that data legitimately)
- Not built from internal WA Health / employer documents (legal/IP risk — use
  public sources only)
- Not an AI/ML model for v0 — plain rules + regex is a feature (auditable,
  testable, explainable to a risk board), not a weakness
- **Not stateful** — v0 does not track patient history, allergy records, or
  prior doses across time. It evaluates one order against one snapshot of
  patient facts, given at the time of the check. Anything requiring memory
  of the patient over time is Layer 2.
- **Not a data source for patient facts** — v0 does not extract age, weight,
  height, or sex from prose. It receives these as structured input alongside
  the drug-order text (see Input Contract below).

## Data sources confirmed safe to use
- RxNorm (NLM) — free, drug name normalization, US-built but universal vocabulary
- openFDA — free, public, no restrictive terms
- DailyMed (NLM) — free drug labeling data
- DrugBank — free for research/academic, PAID license needed for commercial use later
- Australian Medicines Handbook (AMH) + Children's Dosing Companion — reference only,
  don't copy tables verbatim, use to inform your own encoded rules
- Perth Children's Hospital public monographs — same rule: reference, don't republish
- Therapeutic Guidelines / eTG — same rule
- **WHO Child Growth Standards** (0–2 years) — who.int/childgrowth — public,
  LMS parameter tables (CSV/XLS), used clinically in Australia for this age band
- **CDC 2000 Growth Charts** (2–18/20 years) — cdc.gov/growthcharts — public,
  LMS parameter tables (CSV/XLS), used clinically in Australia for this age band
  (this WHO 0–2 + CDC 2–18 combination matches actual Australian clinical practice,
  not just "any public dataset")

## Rulebook format (repeat this per drug)
- Population bands table: dose by age/weight group
- Hard red-flag triggers (what SHOULD block/flag)
- Explicit "do NOT flag" list (alert-fatigue defense — as important as red flags)
- Required inputs to evaluate at all (age/weight, dose, frequency, route)
- Sources cited
- Weight-context tag: does this drug need the weight-appropriateness flag
  (hydrophilic, narrow therapeutic index) or not (already hard-capped per dose)?

### Paracetamol (done)
- Neonate (birth–1mo): 15mg/kg, 6-8hrly, max 60mg/kg/day
- Infant/child (1mo-18yr): 15mg/kg/dose (cap 1g), 4-6hrly PRN, max 60mg/kg/day
  (up to ~75-90mg/kg/day short-term inpatient — flag as "verify," don't hard-block)
- Adult ≥50kg: 500-1000mg, 4-6hrly, max 4g/day
- Adult <50kg: reduced, max 3g/day
- Red flags: single peds dose >1g; daily total over band max; adult >4g/day
  (or >3g/day if <50kg); ambiguous mg/mL units on IV/liquid forms
- Do NOT flag: standard adult 1g QID; peds 15mg/kg 4-6hrly PRN; drug mentioned
  with no dose stated
- Weight-context tag: LOW priority (per-dose cap already protects against
  most obesity-related overdose risk)

### Ibuprofen (drafted, needs source verification against live AMH/PCH before encoding)
- Avoid/verify: under 3 months old — route to clinician rather than dose independently
- Infant/child (3mo–18yr): 5–10mg/kg/dose, 6–8hrly, cap 400mg/dose, max 3 doses/day,
  hard daily ceiling 40mg/kg/day or 2400mg/day (whichever lower)
- Adult: 200–400mg, 4–6hrly PRN. OTC ceiling 1200mg/day; prescription-strength
  regimens run higher under supervision — "verify" band, not hard block
- Red flags: single peds dose >400mg or >10mg/kg; daily total over weight-based max;
  any dose in infant <3 months; adult >1200mg/day with no clinical context noted;
  ambiguous concentration (40mg/mL infant drops vs 20mg/mL suspension)
- Do NOT flag: standard peds 5-10mg/kg 6-8hrly; adult 400mg QID OTC; drug
  mentioned with no dose stated
- Known limitation: dehydration, renal impairment, active varicella are all
  reasons to avoid NSAIDs but aren't detectable from dose text alone —
  document as a limitation, not a gap to fix in v0
- Weight-context tag: LOW priority (per-dose cap already protects)

### Amoxicillin (drafted, needs source verification — genuinely harder drug)
- Standard/first-line indications: ~25mg/kg/dose eight-hourly (Therapeutic Guidelines)
- High-dose indications (CAP, resistant otitis media): 80–90mg/kg/day divided —
  this is standard therapy, not an outlier, for these indications
- Adult: 250–500mg q8h typically; heavier regimens (500mg q8h / 875mg q12h) at
  higher body weights; some empiric pneumonia dosing runs to 4g/day ceiling
- Red flags: pediatric >100mg/kg/day; single dose >~1.5-2g in a child;
  adult >4g/day
- Do NOT flag: anything in the 25–90mg/kg/day pediatric band (deliberately wide —
  a tighter band would flag legitimate high-dose pneumonia therapy constantly);
  adult 250mg–1g tds; drug mentioned with no dose
- Design note: unlike paracetamol/ibuprofen, "correct" dose swings by indication,
  not just weight. v0 keeps bands wide and only hard-blocks clear outliers.
  An optional indication field is a Layer 2 idea if tighter bands are wanted later.
- Weight-context tag: LOW priority (wide band already accommodates most
  weight variance; true outliers are outliers regardless of build)

### Next drugs (deferred until v0 mechanism is proven — do not add before shipping)

## Patient weight-appropriateness flag (v0 feature)

### Why this exists
Actual-body-weight dosing in an obese or underweight patient can be meaningfully
wrong for some drugs — hydrophilic, narrow-therapeutic-index drugs especially.
This is a real, evidence-backed concern (WHO recommends ideal-body-weight dosing
for hydrophilic drugs in obese children specifically), not a nice-to-have.

### Two branches, different mechanisms (age determines which one runs)

**Pediatric branch (age < 18):**
- Input: age (months), sex, weight (kg)
- Look up L, M, S values from WHO (0–2yr) or CDC 2000 (2–18yr) table for the
  child's age/sex
- Compute z-score via the LMS formula, convert to percentile
- Trigger: weight percentile outside expected range for age (suggested v0
  threshold: ≥95th percentile — confirm against clinical judgement before
  encoding as final)
- **Do not** auto-calculate an "ideal weight" and substitute it. Published
  pediatric IBW formulas (5 competing methods) have been shown to
  substantially overestimate true lean body weight in obese children —
  none are accurate enough to silently drive a dose calculation.
  Flag only; let the prescriber decide.

**Adult branch (age ≥ 18):**
- Input: height (cm), weight (kg), sex
- Ideal Body Weight (Devine formula):
  - Male: IBW (kg) = 50 + 2.3 × (height in inches over 5ft)
  - Female: IBW (kg) = 45.5 + 2.3 × (height in inches over 5ft)
  - Edge case: undefined/breaks down under 5ft/152cm — fall back to actual
    weight as IBW below this height. Decide and document this now.
- Trigger: actual weight ≥120–130% of IBW
- Suggested reference figure (may be shown to prescriber, unlike peds):
  Adjusted Body Weight = IBW + 0.4 × (actual weight − IBW). This formula is
  far better validated for adults than any pediatric equivalent — still
  shown as a suggestion via the flag, not silently substituted.

**Missing weight (either branch):**
- Flag as "unverifiable" — do not assume clear, do not silently pass.
  Applies to the described emergency/no-scale-available scenario too:
  age-based weight-estimation shortcuts are documented as unreliable,
  particularly in obese children, so treat an emergency estimate as flagged
  input, not a clean number.

### Flag / override / audit mechanism (shared by both branches, and reused
### for any future flag type)
- Flag outcome is always FLAG, never BLOCK — a weight/age mismatch changes
  *how* to dose, it isn't itself dangerous
- Prescriber resolves via:
  - **Acknowledge** — proceed with dose as generated
  - **Adjust** — prescriber recalculates using their own judgement (v0 does
    not auto-recalculate and re-present a "corrected" dose)
- Both paths require: reviewing user ID + a quick-select reason code
  (not free text, not a silent dismiss — this is what makes the audit trail
  real rather than decorative)
- Reason this matters: your own research found 88–96% override rates in
  traditional hospital CDS due to poor specificity. A frictionless dismiss
  button reproduces that exact failure mode. A one-second quick-select
  reason gives you both an audit trail and, later, data on whether your
  flag threshold itself is miscalibrated.

## Input contract (the decision that unblocks everything else)

**Two separate inputs, never merged into one blob of text:**

1. **Drug order text** — what Extract/regex parses: drug name + dose + unit
   + frequency. Narrow, predictable format — this is what regex is good at.
2. **Patient info** — a structured object passed directly by the calling
   product: `{age, weight_kg, height_cm, sex}`. Not extracted from prose.
   Not guessed at. Always in the same place, every time.

This mirrors a real drug chart: patient demographics sit in their own
labeled box; the medication order is a separate line. Mixing the two into
one paragraph the checker has to parse apart is both less reliable
(phrasing varies, fields get silently missed) and worse UX for the
integrating developer (who already has this data structured on their side).

## Pilot architecture (updated)
1. **Extract** — regex pulls drug name + dose + unit + frequency from the
   drug-order text only
2. **Normalize** — map name to RxNorm code (Panadol/paracetamol/acetaminophen
   → one concept)
3. **Check** — compare against rulebook thresholds (dose rules) +
   weight-context rules (using the separate structured patient-info input)
4. **Decide** — PASS / FLAG / BLOCK, with flag sub-states
   (`FLAG_PENDING` → `FLAG_ACKNOWLEDGED` or `FLAG_ADJUSTED`)
5. **Log** — SHA-256 audit hash + structured JSON, including
   `flag_type`, `reason_selected`, `reviewing_user_id`, `resolved_at`

## Layer 2 (explicitly deferred — written down so it isn't lost, not forgotten)
- Allergy cross-referencing against patient history (needs history, not just
  the current order — v0 is stateless by design)
- Last-dose-time / minimum-interval / cumulative-daily-dose tracking across
  a shift or day
- Multi-source provenance tiers for reported dose times (guardian verbal
  recall vs ambulance handover vs charted transfer paperwork vs unknown) —
  each should carry different confidence weighting once this is built
- Per-hospital custom protocol layer overriding v0 generic defaults, so
  institutions can update their own guidelines without waiting on you
- EHR/FHIR integration — real patient data plumbing, not manually-passed JSON
- Optional indication field for amoxicillin-style indication-dependent drugs,
  to tighten bands beyond the wide v0 default

## Open item — not an engineering decision, needs real advice
Australia's TGA has an exclusion/exemption pathway for clinical decision
support software that gives recommendations only (doesn't replace clinical
judgement, shows the guideline basis for review). v0's transparent-logic,
prescriber-reviews-and-overrides design is directionally aligned with that
category — but classification also depends on clinical significance and how
much a clinician is expected to rely on the output, and that judgement isn't
mine to make. **Get real regulatory/legal advice on this before this tool
goes anywhere near real patient-adjacent testing**, even informally. Doesn't
block building/testing v0 with synthetic data now — does block anything past
that.

## Test suite (updated)
15–20 cases, half dangerous / half normal, per your original plan — now
including weight-mismatch scenarios for both age branches and at least one
missing-weight case per branch.

## What developers evaluating v0 will look for
- Trivial setup — one script, minimal dependencies, runs in minutes
- Stable, documented JSON input/output contract (drug-order text + patient
  object in; decision + reasoning out) — nothing implicit
- Deterministic behavior — same input, same output, always (sell this
  directly against LLM-based guardrail competitors)
- Explainable decisions — every FLAG/BLOCK names the rule and source, never
  a bare score
- Easy extension — can they add drug #4 without touching core logic? First
  thing a technical evaluator tries
- Clean audit trail they'd trust showing their own compliance people
- No licensing landmines (confirm nothing needs a paid DrugBank license
  at this stage)

## Revised build estimate (honest re-scope — was 48hrs for a much smaller v0)
Given the roster (9-day fortnight, 5 days off), framing this as session-based
blocks is more realistic than a continuous 48-hour clock:
- Rulebook encoding (3 drugs, final source-check pass): ~4–6 hrs
- Extraction + normalization (drug-order text only — simpler now that
  patient data isn't part of what regex has to find): ~6–8 hrs
- Growth chart data loading + LMS percentile calculation: ~4–6 hrs
- Adult BMI/IBW/AdjBW calculation (closed-form, no lookup table): ~2–3 hrs
- Flag/override/audit state machine + schema: ~4–6 hrs
- Checking engine integration (dose rules + weight-context rules): ~4–6 hrs
- Logging: ~2–3 hrs
- Test suite (15–20 cases incl. weight scenarios): ~6–8 hrs
- Packaging + README: ~3–4 hrs
- Buffer: ~4–6 hrs

**Total: roughly 40–56 hours** — not wildly beyond the original estimate,
since the input-contract decision actually removed complexity from
extraction even as the weight-flag feature added it elsewhere. Realistic to
spread across 2–3 rostered days off rather than one sprint.

## Three-step plan (bigger picture, unchanged)
1. Build real rulebook for 10-15 drugs (Layer 1 proves out at 3, expand after)
2. Rebuild checker engine around it, stress-test for false positives
3. Quietly hand to 2-3 real developers (direct outreach, not public post) —
   only THEN consider public open-source release

## Key honest findings from research (unchanged)
- Not first-of-kind: Fiddler AI, Databricks AI Gateway, Galileo, Patronus AI,
  Arthur AI Shield all do general LLM guardrails/hallucination detection —
  none have clinically-grounded, weight-band-specific dosing logic. That gap
  is real and defensible.
- CHAI (Coalition for Health AI) attempting the "certification body" idea at
  massive scale and currently struggling — confirms that model is hard even
  with major backing.
- Real, evidenced gap: clinical alert fatigue — traditional hospital CDS
  systems get 88-96% of alerts overridden by clinicians due to poor
  specificity. Low false-positive rate, driven by real clinical judgment,
  is the actual differentiator — not detection ability alone.
- Gap on your side, not competitors': no FHIR/EHR integration yet. Fine for
  a synthetic-data pilot to 2-3 developers; a real wall for actual deployment.
