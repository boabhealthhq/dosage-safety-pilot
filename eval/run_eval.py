"""
Runs the independent evaluation set through the actual checker and reports
honestly on where it agrees and disagrees with ground truth - including a
specific "no decision produced" category, since that's a different failure
mode from PASS (silent miss vs an active, wrong judgement).
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dosage_safety import check_order, PatientInfo, Status
from eval_cases import CASES

SEVERITY = {Status.PASS: 0, Status.FLAG: 1, Status.BLOCK: 2}

results = []

for case_id, desc, text, patient, truth, truth_reason in CASES:
    decisions = check_order(text, patient)
    if not decisions:
        actual = None
    else:
        actual = decisions[0].status
        reasons = decisions[0].reasons
    results.append({
        "id": case_id, "desc": desc, "text": text, "truth": truth,
        "truth_reason": truth_reason, "actual": actual,
        "reasons": reasons if decisions else [],
    })

exact_match = 0
no_decision = 0
dangerous_miss = 0   # truth says danger (FLAG/BLOCK), tool said PASS or nothing - worst category
under_flagged = 0    # truth BLOCK, tool FLAG - caught, less severely
over_flagged = 0     # truth PASS, tool FLAG/BLOCK - false alarm
correctly_lenient = 0  # both PASS

detail_lines = []

for r in results:
    truth, actual = r["truth"], r["actual"]
    tag = None

    if actual is None:
        no_decision += 1
        if truth != Status.PASS:
            dangerous_miss += 1
            tag = "SILENT MISS (dangerous)"
        else:
            tag = "no decision (harmless - truth was PASS anyway)"
    elif actual == truth:
        exact_match += 1
        if truth == Status.PASS:
            correctly_lenient += 1
            tag = "exact match (PASS)"
        else:
            tag = f"exact match ({truth.value})"
    elif SEVERITY[actual] < SEVERITY[truth]:
        if actual == Status.PASS:
            dangerous_miss += 1
            tag = f"MISS: truth={truth.value}, tool said PASS"
        else:
            under_flagged += 1
            tag = f"under-flagged: truth={truth.value}, tool said {actual.value}"
    else:
        over_flagged += 1
        tag = f"over-flagged: truth={truth.value}, tool said {actual.value}"

    detail_lines.append(
        f"[{r['id']}] {tag}\n"
        f"      order: {r['text']!r}\n"
        f"      truth: {truth.value} - {r['truth_reason']}\n"
        f"      tool:  {actual.value if actual else 'NO DECISION'}"
        + (f" - {r['reasons'][0]}" if r["reasons"] else "")
    )

total = len(results)
print("=" * 70)
print(f"INDEPENDENT EVALUATION RESULTS  ({total} cases)")
print("=" * 70)
print(f"Exact match with ground truth:        {exact_match}/{total} ({100*exact_match/total:.0f}%)")
print(f"  of which correctly lenient (PASS):  {correctly_lenient}")
print(f"No decision produced (silent):        {no_decision}")
print(f"Dangerous misses (danger -> PASS/none): {dangerous_miss}")
print(f"Under-flagged (BLOCK -> FLAG):         {under_flagged}")
print(f"Over-flagged (false alarms):           {over_flagged}")
print()
print("=" * 70)
print("CASE-BY-CASE DETAIL")
print("=" * 70)
for line in detail_lines:
    print(line)
    print()

# Regression gate for CI: fails if the score drops below the current
# documented baseline (46/51, i.e. 90%) - NOT if it's simply under 100%,
# since 100% isn't the honest target here. Two remaining misses (P9
# tablet-count multiplication, P17 complex concentration case) are known,
# documented limitations, not bugs to chase to zero. This threshold exists
# to catch a future change making things WORSE, not to demand perfection.
BASELINE_MINIMUM = 46
if __name__ == "__main__":
    print("=" * 70)
    if exact_match < BASELINE_MINIMUM:
        print(
            f"REGRESSION: {exact_match}/{total} is below the documented baseline "
            f"of {BASELINE_MINIMUM}/{total} - something got WORSE, investigate before merging."
        )
        sys.exit(1)
    else:
        print(f"OK: {exact_match}/{total} meets or exceeds the documented baseline of {BASELINE_MINIMUM}/{total}.")
        sys.exit(0)
