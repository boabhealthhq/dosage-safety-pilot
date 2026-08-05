# Dosage Safety Pilot — v0 (paracetamol, ibuprofen, amoxicillin, loratadine, dexamethasone, fentanyl, oxycodone)

<!-- Once this repo is on GitHub, replace YOUR-USERNAME/YOUR-REPO-NAME below
     with the real path and this badge will show live pass/fail status:
     ![CI](https://github.com/YOUR-USERNAME/YOUR-REPO-NAME/actions/workflows/ci.yml/badge.svg)
-->


A rules-based safety layer that checks AI-generated clinical text for
dangerous dosing errors before it reaches a human. Not itself an AI model —
plain regex + a data-driven rulebook, on purpose: auditable, testable, and
explainable to a risk board.

Full design context, decisions, and the Layer 2 roadmap live in
`dosage-safety-pilot-v0-plan.md`. This README covers the code only.

## Quickstart

No dependencies beyond the Python 3 standard library.

```bash
python3 demo.py                       # see the full pipeline on sample text (all 7 drugs)
python3 tests/test_paracetamol.py     # 19 cases
python3 tests/test_ibuprofen.py       # 19 cases
python3 tests/test_amoxicillin.py     # 20 cases
python3 tests/test_loratadine.py      # 10 cases
python3 tests/test_dexamethasone.py   # 13 cases
python3 tests/test_fentanyl.py        # 15 cases
python3 tests/test_oxycodone.py       # 15 cases
```

## How it works

```
AI-generated text  ─┐
                     ├─► Extract ─► Normalize ─► Check ─► Decide ─► Log
Patient info (JSON) ─┘
```

**Two separate inputs, always** — this is the core design decision, not
incidental:

```python
from dosage_safety import check_order, PatientInfo

decisions = check_order(
    "paracetamol 15mg/kg PO 4-6 hourly PRN",   # drug-order text - what Extract parses
    PatientInfo(age_years=5, weight_kg=20),     # patient facts - passed directly, never guessed from text
)
```

`PatientInfo` is never extracted from prose. The calling product is expected
to already have age/weight/height/sex structured on its own side — asking
it to also phrase those facts in text just to have this tool re-parse them
would be less reliable, not more. See the plan doc for the full reasoning.

Each `Decision` carries:
- `status` — `PASS`, `FLAG`, or `BLOCK`
- `reasons` — plain-language, always names the specific rule and number
  compared, never a bare score
- `rule_source` — which reference the threshold came from
- `extracted` — the original order segment, for audit/display

## What's actually encoded (v0 scope)

- **Paracetamol, ibuprofen, and amoxicillin.** Full age/weight bands per
  `dosage_safety/rulebook.py`. Ibuprofen's standard paediatric dose is a
  *range* (5-10mg/kg), not a single point figure like paracetamol's
  15mg/kg - the whole range is treated as normal, only the top of it plus
  a margin gets flagged.
- Single-dose cap check, weight-based dose-rate check, minimum-interval
  check, and daily-total check (the last one **only** runs when the order
  states a single fixed frequency — see note below).
- Ibuprofen additionally: an under-3-months age flag (avoid without
  clinician review, not just a different dosing band), and a two-tier
  adult daily ceiling (1200mg/day OTC → FLAG/verify, 3200mg/day
  prescription-strength → hard BLOCK).
- Amoxicillin is structurally different from the other two: there's no
  single standard mg/kg/dose target, since the correct dose depends on
  what's being treated, not just weight - so there's no per-dose-rate
  check at all. Checking is built around the daily total (deliberately
  wide, 20-90mg/kg/day all treated as normal) and an absolute per-dose cap
  (2000mg) that applies regardless of indication. It also has its own
  third pattern for young infants: a reduced daily ceiling (30mg/kg/day)
  rather than paracetamol's dose-adjustment or ibuprofen's outright avoid.
- Missing age or weight → `FLAG`, never a silent `PASS`.
- Drug mentioned with no dose stated → `PASS` (explicitly out of scope,
  per the plan's own "do not flag" list).

### One deliberate design choice worth knowing about
The daily-total check only fires when the order gives a single, fixed
frequency (e.g. "QID", "6 hourly"). A stated **range** like "4-6 hourly",
especially marked PRN, doesn't tell us how many doses will actually be
given in a day — an earlier version of this engine guessed at the
most-frequent end of the range as a "worst case" and ended up flagging the
textbook-standard "15mg/kg 4-6 hourly PRN" order, which the plan explicitly
lists as something that must never flag. Guessing wrong in that direction
is exactly the false-positive problem this whole project exists to avoid,
so v0 deliberately under-checks range orders on the daily-total dimension
and relies on the minimum-interval and per-dose checks instead, which don't
have this ambiguity.

## v0.7 - four new drugs, including a critical multi-drug extraction bug found in the process
Added **loratadine**, **dexamethasone**, **intranasal fentanyl**, and
**oxycodone** - two low-risk additions and two Schedule 8 opioids that
needed a genuinely different, more conservative design approach.

**A new drug shape - age-banded, not weight-based:**
Loratadine is dosed by fixed amount per age band (5mg for 2-<6yr, 10mg for
6yr+), not mg/kg at all - a fourth distinct pattern alongside paracetamol's
single-point target, ibuprofen's range target, and amoxicillin's
no-target/daily-total-only approach.

**Dexamethasone** uses the same wide-band, absolute-cap pattern as
amoxicillin - legitimate croup dosing alone spans 0.15-0.6mg/kg depending
on protocol, even more indication-variable than amoxicillin.

**Fentanyl and oxycodone are deliberately MORE conservative than every
other drug in this rulebook**, not just "one more drug added the same
way." The "wide band, only flag outliers" philosophy that minimizes false
positives elsewhere would be actively dangerous applied to an opioid - a
paracetamol error causes harm over hours to days, an opioid error can
cause fatal respiratory depression in minutes. Specific design choices:
- A new `PatientInfo.opioid_tolerant` field (default `None` = treated
  conservatively as opioid-naive) - the same dose is correct for a
  tolerant patient and potentially dangerous-if-unverified for a naive
  one, and nothing previously captured this distinction at all.
- A **mandatory disclaimer attached to every decision these two drugs
  return, including PASS** - naming plainly that tolerance status,
  concurrent CNS depressants, and monitoring/naloxone availability are not
  assessed. A clean PASS must never look like "opioid safety fully
  verified."
- Fentanyl includes an explicit **mg/mcg unit-confusion check** - fentanyl
  is dosed in micrograms, a thousand-fold smaller unit than milligrams,
  and this specific mix-up is a well-documented real category of fatal
  dosing error. Writing "1.5mg/kg" instead of "1.5mcg/kg" now BLOCKs
  immediately with an explicit explanation, rather than silently computing
  a massively wrong number.
- Both scoped narrowly on purpose: fentanyl to paediatric **intranasal**
  use only (a different route uses a different, unverified pattern and is
  explicitly flagged as out of scope, not guessed at); oxycodone to
  **immediate-release, opioid-naive initiation** dosing only.

**Two real design bugs found via testing, not test-authoring errors this
time:**
1. Oxycodone's paediatric daily ceiling (1.0mg/kg/day) was inconsistent
   with its own per-dose sourcing - the standard top-of-range dose
   (0.2mg/kg) given at the standard interval (q4h) computes to
   1.2mg/kg/day, which the original ceiling would have wrongly blocked.
   Raised to 1.5mg/kg/day.
2. The infant-under-6-months oxycodone band - the most vulnerable
   population in this rulebook - had safety margins looser than the
   general paediatric band: a dose 3.3x the safe reduced rate only
   produced a mild FLAG, because its absolute cap (2mg) wasn't actually
   calibrated to what a correctly-dosed infant receives. Added a proper
   rate-based BLOCK tier and tightened the cap.

**A critical multi-drug extraction bug, found by testing all 7 drugs
together in one sentence, not by per-drug unit tests:** the
dose-before-drug-name backward-search feature (added in v0.4 for cases
like "1 gram of paracetamol") was reaching into the gap between two
consecutive drugs in an unpunctuated multi-drug sentence - territory that
rightfully belongs to the *previous* drug's forward search. In
`"fentanyl 1.5mcg/kg IN and oxycodone 0.1mg/kg PO 4 hourly"`, oxycodone's
backward search was pulling in **fentanyl's dose**, and because
oxycodone's check function didn't recognize the resulting `mcg/kg` unit
as valid for itself, it silently produced a confident **"PASS - within
standard range"** having checked nothing at all. This is worse than a
random miss - a false claim of verification. Fixed: backward search now
only activates for the first drug in a text, or when a real sentence
terminator genuinely separates two orders - never into an unpunctuated
gap that belongs to the previous drug. Verified directly: re-ran the
exact failing sentence and confirmed oxycodone now correctly captures its
own `0.1mg/kg`, not fentanyl's `1.5mcg/kg`.

**Also fixed along the way:** minute-scale interval recognition
("q5min", "every 10 minutes") - previously invisible to the hour-only
interval patterns, which mattered specifically for opioid redosing safety
checks.

All 111 dev cases (7 drugs) pass. The independent 51-case evaluation score
is unchanged at 90% (46/51), confirming none of this affected the original
three drugs' behavior.

## v0.6 - engineering hardening pass
Prompted by a "read this like a technical evaluator would" review. Two
real structural fixes, plus testing/documentation infrastructure that
didn't exist before:

1. **Rulebook converted from plain dicts to validated dataclasses.** The
   dicts worked, but a typo'd key (e.g. `max_mg_perkg_day` instead of
   `max_mg_per_kg_day`) wouldn't error - it would raise a `KeyError` deep
   in `engine.py`, far from the actual mistake, or silently vanish if the
   accessing code used `.get()` with a default. Confirmed directly: a
   deliberately-introduced typo now fails immediately at construction with
   a clear `TypeError`, not a runtime surprise three files away. Each
   drug's dataclass is shaped to that drug specifically (not forced into
   one generic shape), matching the fact that paracetamol, ibuprofen, and
   amoxicillin genuinely have different band structures.

2. **Drug-checker dispatch converted from an if/elif chain to an explicit
   registry, formalized with a `Protocol`.** This exposed a real related
   bug while fixing it: with the old chain, a drug recognized by
   `normalize_drug()` (has an RxCUI mapping) but missing its `elif` branch
   would silently produce **zero decisions** for that order - no FLAG, no
   error, nothing. Confirmed by simulating exactly that scenario. Now an
   unregistered-but-recognized drug produces an explicit FLAG naming what's
   missing, instead of disappearing.

3. **Fuzz testing** - 3000 hand-rolled randomized/mutated cases (empty
   strings, garbage, huge inputs, implausible patient data, mutated real
   orders) plus a targeted pass for catastrophic regex backtracking with
   inputs up to 100K characters. Zero crashes in either. A proper
   `hypothesis`-based property test (`tests/test_fuzz_hypothesis.py`) is
   included for deeper coverage - written but not run in this build
   environment (no network access to `pip install hypothesis` here); run
   it locally for smarter, auto-shrinking coverage.

4. **FMEA.md** - a structured Failure Mode and Effects Analysis, scoring
   15 failure modes by severity × occurrence × detection, replacing "we
   stress-tested a lot" with a prioritized, re-usable risk register.

5. **ARCHITECTURE.md** - a diagram showing actual data shapes at each
   pipeline boundary (`ExtractedOrder` → `NormalizedDrug` → `Decision` →
   audit dict), not just stage names in prose.

6. **Performance actually measured**, not left uncharacterized: ~4000
   calls/sec on single-order text, ~540/sec on realistic 4-order text, no
   memory growth over 2000 repeated calls, sub-second even on a 50-order
   14KB document.

7. **Linting/type-checking configs added** (`pyproject.toml`, ruff + mypy)
   - `ruff` and `mypy` themselves couldn't be run in this build environment
   (same network limitation), so a manual review pass was done instead:
   found and fixed one real unused import, and wrapped every line over 120
   characters. Run the actual tools locally for a more thorough pass than
   a manual review can achieve.

**Independent evaluation score unchanged at 90% (46/51)** after all of
the above - confirmed by re-running the full eval set against the
refactored code, since a structural refactor should never silently change
behavior.

## v0.5 - input validation for implausible patient data
A quick robustness pass (empty/huge/malformed input, not just messy-but-
plausible clinical text) found two real issues neither prior round had
tested for:
- **Zero patient weight caused an actual crash** (`ZeroDivisionError`) -
  unacceptable in a safety tool regardless of how unlikely the input
- **Negative patient weight silently produced a false PASS** - not because
  anything validated it as safe, but because two negative numbers
  cancelled out in a later division, coincidentally landing on a
  normal-looking figure

Fixed with a shared validator called at the start of every drug check,
before any calculation runs: implausible weight (≤0kg or >300kg) or age
(<0 or >120 years) now returns a clear `FLAG` naming exactly what looked
wrong, instead of crashing or silently computing garbage. Confirmed this
doesn't affect the independent evaluation score (still 90%, since all 51
eval cases use plausible patient values) or any of the 58 dev cases.

## v0.4 - fixes from an independent evaluation round
A 51-case evaluation set was built with ground truth determined *before*
running anything through the tool (to avoid validating it against itself),
deliberately including adversarial cases. Initial score: 71%, with 10
dangerous misses. After fixing the root causes found: **90% (46/51)**, 2
dangerous misses remaining - both are the already-documented liquid
concentration limitation and a narrower tablet-count-multiplication gap,
not new surprises. Every clinical threshold itself was correct throughout -
every miss traced back to text extraction, not the underlying dose rules.

Fixes made:
1. **"Divided daily dose" phrasing** - the highest-priority finding, found
   three separate times. "40mg/kg divided q8h" or "90mg/kg/day divided into
   two doses" were being read as a PER-DOSE figure, sometimes doubling the
   real rate. Now detected via an explicit "/day" unit or the word
   "divided", and correctly converted to a true per-dose equivalent before
   any check runs - shown transparently in the reasons either way.
2. **Spelled-out language** - "every **four** hours", "20mg **per kilo**",
   "**three times a day**", "1 **gram**" were all previously invisible to
   the numeric/abbreviated-only patterns every prior stress-test round had
   used. All now normalized before extraction runs.
3. **A bug the above fixes exposed**: the word "daily" (also a valid
   once-a-day abbreviation) was shadowing an explicit "q6h" stated
   elsewhere in the same order. Interval parsing now tries the explicit
   numeric pattern first, and only falls back to the ambiguous "daily"/"od"
   reading if nothing more explicit was found.
4. **Ibuprofen's under-3-months flag** now fires even when no dose could be
   parsed - previously an unparseable dose caused an early PASS before the
   age check ever ran, silently missing the age-based concern entirely.
5. **Amoxicillin had no per-dose cap for adults at all** - an unusually
   large single dose (e.g. 1750mg, or 3g stat) went unflagged as long as
   the daily total (if computable) stayed under 4000mg. Added a
   verify-tier (>1000mg) and hard-block-tier (>4000mg) per-dose check,
   independent of frequency info, so it also catches large one-off doses.
6. **"IBU" added as a recognized alias** - a common real ED shorthand that
   was previously too short to safely fuzzy-match.
7. **Dose-before-drug-name ordering** - "1 gram of paracetamol" (dose
   stated before the drug name) was invisible, since extraction only
   looked forward from the drug's position. Now searches both directions,
   bounded the same way as before (nearest alias/sentence break), and uses
   whichever side's match is closer - interval/route/PRN parsing
   deliberately stay forward-only, since no case has shown a need for that
   to search backward too.

**Deliberately left unfixed, documented not hidden:**
- Tablet-count multiplication ("2 tablets of 665mg each") - the tool has
  no concept of multiplying a stated tablet count by a per-tablet strength
- Complex multi-part orders combining a concentration statement with a
  stat-load-then-maintenance structure - compounds with the existing,
  still-unresolved liquid-concentration-vs-actual-dose limitation

## v0.2 - fixes from stress-testing against messy, realistic text
A deliberate pass at messy AI-generated-style text (typos, multi-line
formatting, multiple drugs in one sentence, dotted abbreviations) found six
real gaps. All are fixed:

1. **Orders split across multiple lines were losing their dose entirely**
   (silently returning PASS/"no dose stated"). Fixed by anchoring extraction
   to each drug-alias *position* in the full text and scanning forward
   across line breaks, rather than pre-splitting on newlines.
2. **Two drugs in one unpunctuated sentence could have their numbers
   swapped** - a paracetamol order could silently get checked against a
   different drug's dose/frequency. Same fix as #1: the extraction window
   now stops at the *next* recognized drug-alias position, so it can't
   cross into another drug's numbers.
3. **"q.i.d." (with periods) broke the frequency parser** - the periods
   were mistaken for sentence breaks. Fixed with a normalization pass that
   converts common dotted abbreviations (q.i.d., t.i.d., b.i.d., p.r.n.,
   q.d., o.d.) to their plain form before anything else runs.
4. **Decimal doses were at risk of the same problem** (e.g. "2.5g" could
   have been cut at the decimal point). The sentence-break detector now
   explicitly ignores periods with digits on both sides.
5. **Dose ranges ("500-1000mg") silently kept only the upper number** with
   no record a range was ever given. Now detected explicitly, checked
   against the (conservative) upper bound, and always noted in the reasons.
6. **Unrecognized real-world shorthand and typos were completely
   invisible** - "PCM" (a genuine common abbreviation) and "paracetmol"
   (a typo) produced zero output, not even a flag. "PCM" is now a known
   alias. Genuine typos are now caught via single-character edit-distance
   tolerance on words of 5+ letters, and always surfaced transparently in
   the reasons ("matched via typo-tolerance... verify this is correct") -
   never silently treated as certain.

**Known limitation still open, not yet fixed:** text like
"Paracetamol susp 240mg/5mL, give 240mg PO..." (a concentration statement
followed by the actual dose) currently works only because both numbers
happened to match in testing - the extractor doesn't yet distinguish
"this is the formulation strength" from "this is the dose given." Flagging
this honestly rather than claiming it's solved.

## v0.3 - comma-thousands fix and the single-patient contract
A further round of stress-testing against ward-round-style text found two
more things:

1. **"1,000mg" was silently parsed as 0mg.** The comma broke the number
   match, and the regex picked up "000" from what was left. Fixed with a
   number pattern that handles commas correctly - importantly, the fix
   was written to *not* break plain uncommaed numbers like "5000mg" in the
   process, since those are exactly the large, dangerous doses this tool
   most needs to catch correctly.

2. **Multi-patient text produces confidently wrong results.** Text
   describing more than one patient (e.g. a ward-round note covering
   several beds) will have every order in it checked against the *same*
   single `PatientInfo` passed to `check_order()` - which is correct for
   at most one of those orders and silently wrong for the rest. This
   isn't a parsing bug fixable with better regex; it's the input contract.
   **v0's contract: each call to `check_order()` must describe exactly one
   patient.** Callers are responsible for splitting multi-patient text
   (e.g. per bed, per encounter) before calling this tool - it has no way
   to do that splitting itself. This is documented directly in
   `check_order()`'s docstring as well as here.

## What's NOT here yet (see the plan doc for the full Layer 2 list)
- The weight-appropriateness flag (pediatric growth-percentile + adult
  BMI/IBW branches) and its acknowledge/adjust/audit workflow
- Allergy cross-referencing, dose-interval-from-last-dose tracking,
  per-hospital protocol overrides — all explicitly Layer 2
- An indication field for amoxicillin, which would let its currently-wide
  band be tightened per-condition rather than treating the full
  20-90mg/kg/day range as equally normal

## Extending this to a fourth drug
Three worked examples now exist in `engine.py` - `_check_paracetamol`
(single-point mg/kg target), `_check_ibuprofen` (range-based mg/kg
target with an age contraindication), and `_check_amoxicillin`
(indication-dependent, no per-dose target at all, safety checked via
daily total only). Pick whichever pattern is the closer fit for the next
drug, then:
1. Add aliases to `DRUG_ALIASES` in `extract.py`
2. Add the RxCUI mapping to `normalize.py`
3. Define a new dataclass (or reuse an existing band shape if it genuinely
   fits) and the threshold data in `rulebook.py` - see the existing three
   for the pattern. A typo'd field name will fail immediately at import
   time, not silently later.
4. Add a `_check_<drug>()` function in `engine.py` matching the
   `DrugChecker` Protocol (takes `ExtractedOrder, PatientInfo`, returns
   `Decision`), and **register it in the `_CHECKERS` dict** - this is the
   step that used to be an easy-to-forget `elif` branch; forgetting the
   registry entry now produces a visible FLAG instead of the order
   silently vanishing, but it's still worth not forgetting on purpose.
5. Re-run `FMEA.md`'s analysis for the new drug - new drugs may introduce
   failure modes the existing three patterns don't cover.

One thing confirmed by testing: adding each new drug as a real alias
keeps closing gaps in the multi-drug extraction window for free - three
drugs mentioned in one unpunctuated sentence now split correctly with no
manual work needed beyond adding the alias itself.

## v0.8 - CI, and the independent evaluation is now a real, checked-in part of this project
Two gaps closed:

1. **The independent 51-case evaluation only ever existed in a temporary
   sandbox before now** - never actually delivered as part of this
   project, meaning the 90% score was reported but not independently
   re-runnable by anyone else. Moved into `eval/` as a real, permanent
   part of the repo, importing the actual package (not a throwaway copy),
   with a regression-gate exit code: fails if the score drops below the
   documented 46/51 baseline, but doesn't demand 100% - the two remaining
   misses are known, documented limitations (see FMEA.md), not bugs being
   ignored.

2. **`.github/workflows/ci.yml`** - runs automatically on every push and
   pull request. This is the first place several checks actually *execute*
   rather than being configured but unrun: the build environment this
   project was developed in had no network access to install `ruff`,
   `mypy`, or `hypothesis` - a manual code review substituted for the
   first two, and the `hypothesis` property test could only ever be
   written, never actually run, until now. Five separate jobs, each its
   own visible pass/fail check: the 111 dev cases (across three Python
   versions), the independent evaluation, both fuzz tests, lint/type
   checks, and an end-to-end demo smoke test. Every command in the
   workflow was manually traced through a simulated fresh checkout before
   being trusted - see the file itself for what each job actually runs.

Add the CI badge URL at the top of this README once the repo has an
actual GitHub location (see the comment there).

## Other files in this project
- `ARCHITECTURE.md` - pipeline diagram with data shapes at each boundary
- `FMEA.md` - structured, scored failure-mode analysis
- `pyproject.toml` - ruff/mypy config (now actually run in CI, not just configured)
- `eval/` - the independent 51-case evaluation (`eval_cases.py` +
  `run_eval.py`) - re-run anytime with `python eval/run_eval.py`
- `tests/test_fuzz_manual.py` - hand-rolled fuzz test (no dependencies, run anywhere)
- `tests/test_fuzz_hypothesis.py` - property-based fuzz test (needs `pip install hypothesis`, or just let CI run it)
- `.github/workflows/ci.yml` - automatic checks on every push (dev tests, eval, fuzz, lint/type-check, demo smoke test)
