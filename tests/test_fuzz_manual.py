"""
Fuzz test: throws thousands of randomized, mutated, garbage strings at the
checker and confirms it NEVER crashes - only ever returns a valid result
(empty list or a list of well-formed Decisions), regardless of how
malformed the input is.

This is a hand-rolled substitute for a proper hypothesis-based property
test, written because this sandbox has no network access to install
hypothesis. A real hypothesis test file (test_fuzz_hypothesis.py) is
provided alongside this one - run that locally where pip works normally
for deeper, smarter-shrinking coverage. This file still catches the
category of bug that matters most for a safety tool: does malformed input
ever crash the process instead of failing safely.
"""

import os
import random
import string
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dosage_safety import Decision, PatientInfo, check_order  # noqa: E402

random.seed(42)  # reproducible run

REAL_WORDS = [
    "paracetamol", "ibuprofen", "amoxicillin", "panadol", "nurofen",
    "mg", "kg", "PO", "IV", "hourly", "daily", "TDS", "BD", "QID",
    "give", "patient", "dose", "the", "a", "for", "divided", "stat",
]

def random_garbage(length):
    charset = string.printable  # includes control chars, punctuation, digits, letters
    return "".join(random.choice(charset) for _ in range(length))

def random_word_salad(word_count):
    words = []
    for _ in range(word_count):
        if random.random() < 0.3:
            words.append(str(random.randint(-999999, 999999)))
        elif random.random() < 0.5:
            words.append(random.choice(REAL_WORDS))
        else:
            words.append(random_garbage(random.randint(1, 15)))
    return " ".join(words)

def random_patient():
    # deliberately include implausible values sometimes - the validator
    # added in v0.5 should catch these as FLAG, not crash
    age = random.choice([
        random.uniform(0, 120), random.uniform(-100, 0),
        random.uniform(120, 10000), None,
    ])
    weight = random.choice([
        random.uniform(0.1, 300), random.uniform(-100, 0),
        0, random.uniform(300, 100000), None,
    ])
    return PatientInfo(age_years=age, weight_kg=weight)


def run(n_cases=3000):
    crashes = []
    malformed_results = []

    for i in range(n_cases):
        kind = i % 5
        if kind == 0:
            text = random_garbage(random.randint(0, 200))
        elif kind == 1:
            text = random_word_salad(random.randint(1, 30))
        elif kind == 2:
            text = ""
        elif kind == 3:
            text = " " * random.randint(0, 50) + "\n" * random.randint(0, 10)
        else:
            # realistic-ish but mutated: take a real order and corrupt it
            base = random.choice([
                "paracetamol 15mg/kg PO 4-6 hourly PRN",
                "ibuprofen 200mg PO QID",
                "amoxicillin 40mg/kg divided q8h",
            ])
            chars = list(base)
            for _ in range(random.randint(1, 5)):
                pos = random.randint(0, len(chars) - 1)
                chars[pos] = random.choice(string.printable)
            text = "".join(chars)

        patient = random_patient()

        try:
            result = check_order(text, patient)
            if not isinstance(result, list):
                malformed_results.append((text, patient, f"returned {type(result)}, not a list"))
                continue
            for d in result:
                if not isinstance(d, Decision):
                    malformed_results.append((text, patient, f"list contained {type(d)}, not a Decision"))
                if d.status is None:
                    malformed_results.append((text, patient, "Decision.status was None"))
        except Exception as e:
            crashes.append((text, patient, type(e).__name__, str(e)))

    print(f"Ran {n_cases} randomized/mutated cases.")
    print(f"Crashes: {len(crashes)}")
    print(f"Malformed results (wrong type/shape): {len(malformed_results)}")

    if crashes:
        print("\n--- CRASH DETAILS (first 10) ---")
        for text, patient, exc_type, exc_msg in crashes[:10]:
            print(f"  text={text!r}")
            print(f"  patient=age:{patient.age_years} weight:{patient.weight_kg}")
            print(f"  {exc_type}: {exc_msg}")
            print()

    if malformed_results:
        print("\n--- MALFORMED RESULT DETAILS (first 10) ---")
        for text, patient, issue in malformed_results[:10]:
            print(f"  text={text!r} -> {issue}")

    return len(crashes) == 0 and len(malformed_results) == 0


if __name__ == "__main__":
    ok = run()
    print("\n" + ("PASS - no crashes, no malformed results" if ok else "FAIL - see details above"))
    sys.exit(0 if ok else 1)
