# Failure Mode and Effects Analysis (FMEA)

## Methodology
Every failure mode below is rated on three axes, 1-10:
- **Severity (S)** — how bad the outcome is if this happens and reaches a human unflagged
- **Occurrence (O)** — how likely this specific input pattern is in real AI-generated clinical text
- **Detection (D)** — how likely the *current* system is to catch this before it reaches a human (10 = would definitely NOT be caught)

**RPN (Risk Priority Number) = S × O × D.** Higher = more urgent. This is a
living document — re-score after every fix, and add new rows as new
failure modes are found (via stress-testing, evaluation, or production use).

Everything here was found through six-plus rounds of stress-testing, a
51-case independent evaluation, and a targeted robustness/fuzz pass across
this build. This document exists to turn that exploratory process into
something systematic and re-usable going forward, not to claim these are
newly discovered - most are already in the README, cross-referenced below.

## High priority (RPN > 200)

| # | Failure mode | S | O | D | RPN | Status | Notes |
|---|---|---|---|---|---|---|---|
| 0 | Multi-drug dose-stealing: in an unpunctuated multi-drug sentence, one drug's extraction could silently capture a DIFFERENT drug's dose, and if the resulting unit wasn't recognized, produce a confident but completely fabricated "PASS - within standard range" | 9 | 3 | 9 (pre-fix) | 243 (pre-fix) | **Found and fixed (v0.7)** | Found via testing all 7 drugs together, not by any per-drug unit test. Worse than a random miss - a false claim of verification is actively misleading, not just silent. Root cause: the dose-before-drug-name backward-search feature (v0.4) reached into territory between two consecutive aliases that rightfully belonged to the previous drug. Fixed by only allowing backward search for the first drug in a text or across a real sentence terminator. Residual risk: similar cross-drug interactions in untested phrasing patterns can't be fully ruled out without exhaustive multi-drug fuzz testing, which doesn't yet exist. |
| 1 | Drug name unrecognized (novel brand, short abbreviation, severe typo) - order becomes completely invisible, zero decision, zero log entry | 8 | 4 | 9 | 288 | Partially mitigated | Fuzzy-match (1-char typo tolerance, 5+ letter words) + explicit short aliases (PCM, IBU) cover known cases. Structurally can't cover unknown-unknowns - any future brand name or abbreviation not yet added is invisible by default. |
| 2 | Rulebook staleness - no mechanism detects when AMH/eTG guidance has changed since a threshold was encoded | 6 | 6 | 8 | 288 | **Not mitigated** | No "last verified" date per threshold, no alert mechanism. Real risk for any deployment running longer than a few months. Extends to fentanyl/oxycodone research literature too, which moves at least as fast as AMH/eTG. |
| 3 | Concentration-vs-administered-dose confusion (e.g. "120mg/5mL, give 20mL" extracts 120mg, not the real 480mg) | 8 | 5 | 7 | 280 | **Known, documented, unmitigated** | Confirmed dangerous via independent evaluation (case P6: real 2x overdose in a 4kg infant read as a correctly-dosed order). Sometimes coincidentally correct when volume happens to equal one concentration unit - not reliable. Higher stakes now that opioids are in the rulebook - a concentration mix-up on fentanyl or oxycodone liquid formulations would be more dangerous than on paracetamol. |
| 4 | Structural "catch what we can parse" limitation - any order the extractor fails to parse is invisible, not flagged as unverifiable | 7 | 4 | 9 | 252 | **Architectural, ongoing** | This is the root cause underlying rows 1, 3, 5, 6, 9 below - not a single bug but the nature of a regex-extraction approach. Six rounds of hardening have narrowed this substantially but can't close it structurally without a different extraction approach entirely (e.g. LLM-assisted extraction with its own new risk surface). |
| 5 | No allergy cross-referencing at all | 9 | 3 | 10 | 270 | **Explicitly out of scope (Layer 2)** | Highest per-incident severity in this whole table if it ever happened, but zero code path currently touches allergy data - not a bug, a scope boundary. Must be resat before this could ever be positioned as more than a dosing-only check. |

## Medium priority (RPN 100-200)

| # | Failure mode | S | O | D | RPN | Status | Notes |
|---|---|---|---|---|---|---|---|
| 6 | No drug-drug interaction checking | 6 | 3 | 9 | 162 | Out of scope (Layer 2) | e.g. concurrent paracetamol + ibuprofen is individually fine but not cross-checked as a pair |
| 7 | No audit-record persistence | 4 | 8 | 5 | 160 | **Caller's responsibility, undocumented as a requirement** | `to_audit_record()` generates the hashed record but nothing in v0 writes it anywhere durable - if the integrating product doesn't persist it, the "audit trail" claim is aspirational, not real. Should be called out explicitly in integration docs, not assumed. |
| 8 | Amoxicillin's wide legitimate band (20-90mg/kg/day) can't distinguish "correct for indication A" from "wrong for indication B" | 6 | 4 | 6 | 144 | **Known, documented (no indication field in v0)** | Deliberate design tradeoff, not an oversight - see rulebook.py comments |
| 9 | Tablet-count multiplication not understood ("2 tablets of 665mg each") | 6 | 3 | 8 | 144 | **Known, documented, unmitigated** | Confirmed via independent evaluation (case P9) |
| 10 | Engineering tolerance margins (10%, 15% dose-rate tolerances; plausibility bounds) are judgment calls, not independently clinically validated | 5 | 5 | 4 | 100 | **Actively being addressed** | This is specifically what the pharmacist review is for - flagged explicitly in the review document sent for clinical sign-off |
| 11 | Opioid tolerance status unknown - the same fentanyl/oxycodone dose can be routine for a tolerant patient and needs verification for a naive one | 7 | 6 | 4 | 168 | **Partially mitigated** | `PatientInfo.opioid_tolerant` field added (v0.7) lets a caller declare tolerance explicitly; when not provided, conservatively assumed naive and a mandatory disclaimer is attached to every decision (PASS included). Does NOT encode actual tolerant-patient dosing thresholds - a declared-tolerant patient gets flagged for independent verification, not auto-cleared against a different ceiling this tool doesn't have. |

## Lower priority (RPN < 100)

| # | Failure mode | S | O | D | RPN | Status | Notes |
|---|---|---|---|---|---|---|---|
| 11 | Route of administration (PO vs IV) not distinguished - same thresholds applied regardless | 5 | 3 | 6 | 90 | Known, documented | IV formulations have their own dosing-error history in real clinical practice; not yet reflected here |
| 12 | Complex multi-part orders (stat-load-then-maintenance combined with concentration language) | 6 | 2 | 7 | 84 | Known, documented, unmitigated | Compounds with row 3 |
| 13 | No prescriber identity capture | 3 | 7 | 3 | 63 | Deferred to Layer 2 | Requires the calling product to supply an authenticated identity - this layer can't invent one; explicitly documented as an interface requirement for real deployment |
| 14 | Crash on implausible patient data (zero/negative weight) | 7 | 2 | 3 | 42 | **Fixed (v0.5)**, residual risk of other unfound malformed-input categories | Mitigated by a shared validator + a 3000-case hand-rolled fuzz pass and a `hypothesis`-based property test file (run separately, network access needed) - both found zero crashes post-fix |
| 15 | Catastrophic regex backtracking (ReDoS) under adversarial structured input | 6 | 1 | 2 | 12 | **Tested, not found** | Deliberately pathological inputs up to 100K characters tested; worst case ~1.4s, no exponential blowup pattern found. Re-verified after adding 4 more drugs (v0.7): confirmed linear scaling up to 160K characters (0.5s -> 1.0s -> 2.1s -> 4.2s doubling cleanly with input size) - no quadratic or worse behavior introduced by the additional drug logic. |
| 16 | Fentanyl (route) and oxycodone (formulation) narrow scope - IV/other-route fentanyl and extended-release oxycodone are not covered | 5 | 3 | 2 | 30 | **Well-mitigated** | Unlike row 11 (general route blindness for the other drugs), an out-of-scope route for fentanyl produces an explicit FLAG naming exactly what wasn't checked, rather than silently applying the wrong thresholds - a deliberate design choice given the stakes for this drug class. |

**Positive note, not a failure mode:** the mg/mcg unit-confusion risk for
fentanyl specifically - a well-documented real category of fatal dosing
error, given the drug is dosed in micrograms, a thousand-fold smaller unit
than milligrams - is explicitly checked and hard-BLOCKed (v0.7), verified
directly by testing "1.5mg/kg" against the real "1.5mcg/kg" standard dose.
Worth naming as evidence the conservative design choice for this drug
class is doing real work, not just adding caveats.

## What to actually do with this table
- **Rows 1-4** are the ones worth real engineering time before any deployment beyond a synthetic-data pilot to a handful of developers.
- **Row 5** (allergy checking) isn't a bug to fix - it's a scope decision. If this tool is ever positioned as more than "dosing math," that positioning needs to be corrected before row 5 becomes a genuine liability rather than a known boundary.
- **Row 2** (rulebook staleness) has no code fix - it needs a process: a recurring calendar reminder to re-verify thresholds against live AMH/eTG, tracked per-drug, not just "verify before this goes live" once.
- Re-run this analysis after each new drug is added, since new drugs may introduce failure modes not covered by paracetamol/ibuprofen/amoxicillin's three patterns.
- **Row 0 is the single most important lesson from adding drugs 4-7**: per-drug unit tests, however thorough, cannot find cross-drug interaction bugs. The multi-drug dose-stealing issue only surfaced when all 7 drugs were tested together in one realistic sentence. Any future drug addition should include a multi-drug integration test alongside its own unit tests, not as an afterthought.
