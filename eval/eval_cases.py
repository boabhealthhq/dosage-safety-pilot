"""
Independent evaluation set for the Dosage Safety Pilot.

METHODOLOGY NOTE: unlike the 58 development test cases (which were written
alongside the code and used to build/verify the logic), the ground truth
here was determined from clinical reasoning FIRST, independent of what the
code would output, specifically to avoid validating the tool against
itself. Several cases are deliberately adversarial - designed to probe
known limitations (concentration-vs-dose confusion, "divided daily dose"
phrasing, short unrecognized abbreviations) rather than cases hand-picked
to make the tool look good. Where the ground truth itself is genuinely
debatable, that's noted honestly rather than forced to a clean answer.

Ground truth status meanings:
  PASS  = a competent clinician would not give this a second look
  FLAG  = worth a human's attention/verification, not clearly dangerous
  BLOCK = genuinely unsafe as written, should not proceed
"""

import sys

sys.path.insert(0, '..')
from dosage_safety import PatientInfo, Status

# (id, description, order_text, patient, ground_truth, ground_truth_reasoning)
CASES = [

    # ============ PARACETAMOL ============
    ("P1", "no explicit frequency, dose itself correct",
     "Panadol 250mg PO for a feverish child", PatientInfo(age_years=4, weight_kg=16),
     Status.PASS, "250mg vs expected 15mg/kg*16kg=240mg - well within tolerance, nothing dangerous stated"),

    ("P2", "casual phrasing, genuinely dangerous adult regimen",
     "Give the patient 1 gram of paracetamol every four hours around the clock", PatientInfo(age_years=45, weight_kg=80),
     Status.BLOCK, "1000mg q4h = 6000mg/day, well over the 4000mg/day adult ceiling - real overdose risk"),

    ("P3", "textbook standard peds order",
     "Paracetamol 15 mg/kg every 4 to 6 hours as needed for pain", PatientInfo(age_years=6, weight_kg=20),
     Status.PASS, "standard dosing, standard interval"),

    ("P4", "no dose stated at all",
     "continue home medications including panadol", PatientInfo(age_years=6, weight_kg=20),
     Status.PASS, "nothing quantifiable to check"),

    ("P5", "adult dose close to but not over the cap",
     "Tylenol 650mg PO q4h PRN", PatientInfo(age_years=50, weight_kg=70),
     Status.PASS, "650mg q4h=3900mg/day, under the 4000mg cap - legal but close to the edge"),

    ("P6", "ADVERSARIAL: liquid concentration vs actual administered dose",
     "Paracetamol drops 80mg/mL, give 1.5mL PO for infant", PatientInfo(age_years=0.3, weight_kg=4),
     Status.BLOCK, "real dose = 80*1.5=120mg for a 4kg infant = 30mg/kg, DOUBLE the standard 15mg/kg - genuinely dangerous, but the concentration figure (80mg) is what's extractable from text"),

    ("P7", "typo + single stat dose",
     "paracetmaol 1g PO stat", PatientInfo(age_years=40, weight_kg=75),
     Status.PASS, "1g single dose is standard for a 75kg adult"),

    ("P8", "multi-line structured/labeled order format",
     "Medication: Paracetamol\nDose: 15mg/kg\nRoute: Oral\nFrequency: 4-6 hourly PRN",
     PatientInfo(age_years=5, weight_kg=18),
     Status.PASS, "standard order, just formatted as labeled fields rather than prose"),

    ("P9", "ADVERSARIAL: tablet count multiplication the tool can't do",
     "Give panadol osteo 2 tablets (665mg each) three times daily", PatientInfo(age_years=55, weight_kg=70),
     Status.FLAG, "real dose = 2*665=1330mg TDS=3990mg/day, right at the edge of the 4000mg cap - the tool has no concept of 'N tablets of Xmg each' multiplication"),

    ("P10", "neonate, dose slightly under exact calc but reasonable",
     "Neonate day 3 of life, weight 3.2kg, paracetamol 45mg PO q8h", PatientInfo(age_years=0.008, weight_kg=3.2),
     Status.PASS, "expected 15*3.2=48mg, 45mg is a reasonable real-world rounding"),

    ("P11", "IV route, at the cap boundary",
     "paracetamol 1000mg IV q6h", PatientInfo(age_years=38, weight_kg=68),
     Status.FLAG, "1000mg q6h=4000mg/day, exactly at the general adult ceiling. Ground truth "
     "updated (was PASS) after route-caution checking was added - IV paracetamol dosing errors "
     "are a real, documented category of harm, and the tool now correctly flags that IV wasn't "
     "separately verified, rather than silently treating it the same as oral."),

    ("P12", "dangerous dose disguised in casual conversational phrasing",
     "Since the fever hasn't come down, let's try upping the panadol to 20 mg per kilo every four hours for now",
     PatientInfo(age_years=6, weight_kg=20),
     Status.BLOCK, "20mg/kg q4h = 120mg/kg/day, double even the 60mg/kg/day standard max"),

    ("P13", "conservative/low but safe adult dose",
     "500 mg paracetamol tablet, PO, twice daily", PatientInfo(age_years=60, weight_kg=65),
     Status.PASS, "1000mg/day total, well under cap - arguably under-treating but not dangerous"),

    ("P14", "vague, no extractable number",
     "paracetamol dose as per weight", PatientInfo(age_years=6, weight_kg=20),
     Status.PASS, "nothing quantifiable to check"),

    ("P15", "boundary precision test, exactly at reduced adult cap",
     "APAP 3g daily divided q6h", PatientInfo(age_years=70, weight_kg=45),
     Status.PASS, "3000mg/day for a <50kg adult - exactly at, not over, the 3000mg reduced cap"),

    ("P16", "note referencing a dose with no new quantifiable order",
     "give an extra dose of panadol since it's been 5 hours", PatientInfo(age_years=8, weight_kg=25),
     Status.PASS, "nothing quantifiable stated"),

    ("P17", "ADVERSARIAL: complex stat-load-then-maintenance, concentration confusion",
     "Paracetamol elixir 120mg/5ml. Administer 20ml stat then 10ml QDS.", PatientInfo(age_years=3, weight_kg=14),
     Status.FLAG, "real stat dose = 20*(120/5)=480mg vs expected ~210mg (15mg/kg*14) - 2.3x expected, worth a human's attention even if not immediately fatal"),

    # ============ IBUPROFEN ============
    ("I1", "liquid dose where volume happens to equal one concentration unit",
     "Nurofen for children 5mL (100mg/5mL suspension), give 5mL PO tds", PatientInfo(age_years=3, weight_kg=15),
     Status.PASS, "real dose=100mg TDS=300mg/day=20mg/kg/day, safely within range"),

    ("I2", "standard adult OTC dosing",
     "ibuprofen 200mg PO q6h", PatientInfo(age_years=35, weight_kg=70),
     Status.PASS, "800mg/day, under the 1200mg OTC ceiling"),

    ("I3", "prescription-strength regimen, legitimate but worth verifying",
     "Advil 800mg PO tds", PatientInfo(age_years=48, weight_kg=85),
     Status.FLAG, "2400mg/day - a real prescription-strength regimen for e.g. arthritis, not routine OTC, worth confirming intent"),

    ("I4", "vague volume, no usable concentration given",
     "give bubs some nurofen, about 2.5mL should do it", PatientInfo(age_years=1.5, weight_kg=11),
     Status.PASS, "nothing reliably quantifiable without a stated concentration"),

    ("I5", "per-dose rate moderately above standard range",
     "Ibuprofen 12mg/kg PO 6-8 hourly PRN", PatientInfo(age_years=5, weight_kg=22),
     Status.FLAG, "12mg/kg is 20% above the top of the standard 5-10mg/kg range, worth verifying"),

    ("I6", "prescription-strength adult regimen for severe pain",
     "Nurofen 400mg PO 4 hourly for severe pain", PatientInfo(age_years=41, weight_kg=78),
     Status.FLAG, "2400mg/day - prescription range, not routine, worth confirming intent"),

    ("I7", "elevated stat dose, PRN repeat",
     "ibuprofen 15mg/kg stat then repeat in 8 hours if needed", PatientInfo(age_years=6, weight_kg=20),
     Status.FLAG, "15mg/kg is 50% above the standard 10mg/kg top - worth verifying even as a one-off"),

    ("I8", "liquid dose requiring real multiplication, still safe",
     "brufen syrup, 7.5mL of 100mg/5mL, three times a day", PatientInfo(age_years=4, weight_kg=16),
     Status.PASS, "real dose=150mg TDS=450mg/day=28mg/kg/day, safely within range"),

    ("I9", "prescription-strength, worth verifying",
     "Motrin 600mg PO q8h", PatientInfo(age_years=44, weight_kg=82),
     Status.FLAG, "1800mg/day - between OTC and prescription ceiling, worth confirming"),

    ("I10", "young infant, safe standard dosing",
     "ibuprofen 5mg/kg PO bd", PatientInfo(age_years=0.67, weight_kg=9),
     Status.PASS, "10mg/kg/day, safely within range for an 8-month-old"),

    ("I11", "under 3 months - real contraindication concern",
     "Nurofen 2.5mL PO for a 2 month old with fever", PatientInfo(age_years=0.17, weight_kg=5.5),
     Status.FLAG, "ibuprofen generally avoided under 3 months without specific clinician review"),

    ("I12", "clearly dangerous, casual phrasing",
     "just double up on the nurofen dose to 20mg per kilo since the pain is bad, keep the same 6 hourly schedule",
     PatientInfo(age_years=10, weight_kg=32),
     Status.BLOCK, "20mg/kg*32kg=640mg per dose, well over the 400mg hard cap"),

    ("I13", "standard safe toddler dosing",
     "ibuprofen 100mg PO tds", PatientInfo(age_years=2, weight_kg=13),
     Status.PASS, "within 5-10mg/kg range, 23mg/kg/day well under cap"),

    ("I14", "ADVERSARIAL: unrecognized short abbreviation",
     "IBU 450mg PO stat", PatientInfo(age_years=40, weight_kg=75),
     Status.FLAG, "450mg single stat dose in an adult is a bit above the typical 400mg figure, worth a glance - but 'IBU' is too short to safely alias or fuzzy-match, so this will likely go completely unseen"),

    ("I15", "genuinely dangerous, exceeds both per-dose and daily caps",
     "ibuprofen 30mg/kg PO 6 hourly", PatientInfo(age_years=8, weight_kg=26),
     Status.BLOCK, "780mg/dose (over 400mg cap) and 3120mg/day (over 2400mg absolute cap) - double violation"),

    ("I16", "safe standard adult dosing",
     "please charter nurofen 200mg tablets, 1 tab PO tds for arthritis flare", PatientInfo(age_years=58, weight_kg=60),
     Status.PASS, "600mg/day, well under OTC ceiling"),

    ("I17", "liquid dose, safe, concentration figure coincidentally still in-range",
     "ibuprofen suspension 3.5mL (200mg/5mL) tds", PatientInfo(age_years=8, weight_kg=28),
     Status.PASS, "real dose=140mg TDS=420mg/day=15mg/kg/day, safely within range"),

    ("I18", "ADVERSARIAL: unusual 'loading dose' phrasing for a drug that doesn't typically use one",
     "Nurofen 1200mg loading dose then 400mg PO qid", PatientInfo(age_years=42, weight_kg=90),
     Status.FLAG, "the 'loading dose' framing itself is clinically unusual for ibuprofen and worth a human's attention regardless of the specific numbers"),

    # ============ AMOXICILLIN ============
    ("A1", "standard safe pediatric dosing",
     "Amoxil 250mg PO tds for 5 days", PatientInfo(age_years=6, weight_kg=22),
     Status.PASS, "34mg/kg/day, comfortably within the wide legitimate band"),

    ("A2", "ADVERSARIAL: daily-total stated with 'divided' framing, not per-dose",
     "amoxicillin 90mg/kg/day divided into two doses", PatientInfo(age_years=5, weight_kg=20),
     Status.PASS, "this states 90mg/kg PER DAY divided BD = 45mg/kg per actual dose, a legitimate high-dose regimen - real risk: text says 'mg/kg' which the tool always reads as a PER-DOSE figure, so it may compute this as 90mg/kg per dose (180mg/kg/day) instead"),

    ("A3", "standard adult dosing",
     "amoxycillin 500mg tds", PatientInfo(age_years=32, weight_kg=68),
     Status.PASS, "1500mg/day, well within range"),

    ("A4", "ADVERSARIAL: unusually large single stat dose, no adult per-dose cap exists",
     "amoxicillin 3g PO stat as prophylaxis", PatientInfo(age_years=45, weight_kg=75),
     Status.FLAG, "3g as a single dose is unusually large even for prophylactic use and worth verifying context - current code has no per-dose cap check for adults at all"),

    ("A5", "liquid dose, concentration matches actual dose exactly",
     "Amoxil oral suspension 125mg/5mL, give 5mL PO tds", PatientInfo(age_years=2, weight_kg=12),
     Status.PASS, "real dose=125mg TDS=375mg/day=31mg/kg/day, within band"),

    ("A6", "textbook high-dose otitis media regimen - must not be flagged",
     "amoxicillin 45mg/kg PO bd for otitis media", PatientInfo(age_years=4, weight_kg=18),
     Status.PASS, "45mg/kg BD=90mg/kg/day - this is THE standard high-dose AOM regimen, should never be flagged"),

    ("A7", "interval too frequent for a neonate's renal clearance",
     "amoxicillin 20mg/kg PO tds", PatientInfo(age_years=0.03, weight_kg=3.5),
     Status.BLOCK, "TDS (8hrly) is below the 12hrly minimum appropriate for a neonate's immature renal clearance"),

    ("A8", "infant under 3mo, exactly at the reduced ceiling",
     "amoxicillin 15mg/kg PO bd", PatientInfo(age_years=0.15, weight_kg=4.5),
     Status.PASS, "30mg/kg/day, exactly at (not over) the appropriate reduced infant ceiling"),

    ("A9", "standard higher adult regimen",
     "moxatag 875mg PO bd", PatientInfo(age_years=50, weight_kg=90),
     Status.PASS, "1750mg/day, a common real-world regimen e.g. for sinusitis"),

    ("A10", "genuinely dangerous, disguised in casual phrasing",
     "given how bad the infection is, let's bump amoxicillin up to 60mg/kg per dose, three times a day",
     PatientInfo(age_years=7, weight_kg=25),
     Status.BLOCK, "180mg/kg/day - double the verify threshold and over the absolute 4000mg/day cap"),

    ("A11", "liquid dose, concentration matches actual dose",
     "Amoxil susp, 1 teaspoon (5mL) of 250mg/5mL, PO tds", PatientInfo(age_years=5, weight_kg=19),
     Status.PASS, "real dose=250mg TDS=750mg/day=39mg/kg/day, within band"),

    ("A12", "no dose stated",
     "amoxicillin dose to be confirmed by pharmacy", PatientInfo(age_years=6, weight_kg=20),
     Status.PASS, "nothing quantifiable to check"),

    ("A13", "ADVERSARIAL: unusually large single dose, stays under daily cap so likely unflagged",
     "Amoxycillin 1750mg PO bd", PatientInfo(age_years=55, weight_kg=95),
     Status.FLAG, "1750mg is an atypically large single dose (typical max ~1000mg/dose) even though the 3500mg/day total stays under the absolute cap - no per-dose check exists for adults"),

    ("A14", "safe single stat dose",
     "amoxicillin 25mg/kg stat single dose for strep throat prophylaxis contact", PatientInfo(age_years=9, weight_kg=30),
     Status.PASS, "750mg one-time, reasonable and well under the 2000mg per-dose cap"),

    ("A15", "clearly excessive, caught by absolute daily cap regardless",
     "amoxicillin 2200mg PO tds", PatientInfo(age_years=48, weight_kg=80),
     Status.BLOCK, "6600mg/day, well over the 4000mg absolute adult ceiling"),

    ("A16", "ADVERSARIAL: same 'divided' daily-total phrasing pattern as A2, second example",
     "Give amoxicillin 40mg/kg divided q8h", PatientInfo(age_years=6, weight_kg=21),
     Status.PASS, "40mg/kg/day divided TDS is a normal, common regimen - real risk is the tool reading '40mg/kg' as a per-dose figure, implying 120mg/kg/day"),
]

if __name__ == "__main__":
    print(f"{len(CASES)} independent evaluation cases loaded")
    from collections import Counter
    print(Counter(c[4].value for c in CASES))
