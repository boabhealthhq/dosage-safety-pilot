# Dosage Safety Pilot — v0

A rules-based safety layer that checks AI-generated clinical text for
dangerous medication dosing errors before it reaches a human. Not itself
an AI model — plain regex + a data-driven rulebook, on purpose: auditable,
testable, and explainable to a risk board.

Covers 7 drugs: paracetamol, ibuprofen, amoxicillin, loratadine,
dexamethasone, fentanyl, oxycodone. The last two (opioids) use a
deliberately more conservative design than the other five, given the
higher stakes of an opioid dosing error.

## Quickstart

No dependencies beyond the Python standard library.

```bash
python3 demo_single_file.py       # see the pipeline run on sample text (all 7 drugs)
python3 test_all_single_file.py   # full test suite - 111 cases across all 7 drugs
```

Expect the test run to end with: `111 passed, 0 failed, 111 total`

## What this is
Sits between an AI product's clinical text output and the end user.
Extracts a drug name, dose, and frequency from free text, checks it
against sourced clinical thresholds, and returns PASS / FLAG / BLOCK with
a plain-language reason naming the exact rule that fired — never a bare
score. Does not diagnose, prescribe, or touch an EHR.

## Independently evaluated, not just self-tested
Beyond the 111 hand-written test cases, this has been checked against a
separate 51-case evaluation set where the correct answer was decided
*before* running anything through the tool, specifically to avoid
validating it against itself. Score: 90% (46/51), with the two remaining
misses being known, documented limitations rather than hidden bugs.

## Current state - single-file version
This repository currently holds the two-file convenience version of the
project, built so it can run with zero setup. A fuller version exists
with the code split into proper modules, a structured risk analysis
(FMEA), an architecture diagram, and automated CI — to be added to this
repository as a follow-up, not missing by oversight.

## License
MIT, with an added clinical-safety notice - see `LICENSE`. This is a
decision-support pilot, not a certified medical device. Every FLAG and
BLOCK requires human clinical review before acting on it.
