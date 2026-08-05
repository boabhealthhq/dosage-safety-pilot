"""
Check + Decide steps.

check_order() is the main entry point: takes AI-generated order text and a
separate structured PatientInfo, returns one Decision per recognized order.

Every FLAG/BLOCK names the specific rule that fired and the number it was
compared against - never a bare score. That's a deliberate product
requirement, not just a nice-to-have: it's what makes the audit trail
defensible and what a developer evaluating this tool will check first.
"""

from typing import Protocol

from .extract import extract_orders
from .normalize import normalize_drug
from .rulebook import PARACETAMOL, IBUPROFEN, AMOXICILLIN, LORATADINE, DEXAMETHASONE, FENTANYL, OXYCODONE
from .models import PatientInfo, Decision, Status, ExtractedOrder

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
