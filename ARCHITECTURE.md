# Architecture

## Pipeline overview, with data shapes at each boundary

```mermaid
flowchart TD
    subgraph Input
        A["AI-generated clinical text<br/>(str)"]
        B["PatientInfo<br/>age_years, weight_kg,<br/>height_cm, sex"]
    end

    A --> C["EXTRACT<br/>extract_orders(text)"]

    C --> D["list of ExtractedOrder<br/>drug_name_raw, drug_canonical,<br/>dose_value, dose_unit,<br/>interval_low_hr, interval_high_hr,<br/>route, prn, is_fuzzy_match,<br/>dose_is_range, dose_is_daily_total"]

    D --> E["NORMALIZE<br/>normalize_drug(drug_canonical)"]

    E --> F["NormalizedDrug<br/>canonical_name, rxcui<br/>(or None if unrecognized -<br/>order silently skipped)"]

    F --> G{"CHECK dispatch<br/>_CHECKERS registry lookup"}
    B -.-> G

    G -->|paracetamol| H1["_check_paracetamol()"]
    G -->|ibuprofen| H2["_check_ibuprofen()"]
    G -->|amoxicillin| H3["_check_amoxicillin()"]
    G -->|unregistered drug| H4["explicit FLAG:<br/>'recognized but not verified'<br/>(v0.6 safety net)"]

    H1 --> I
    H2 --> I
    H3 --> I
    H4 --> I

    I["Decision<br/>status: PASS/FLAG/BLOCK<br/>reasons: list of str<br/>rule_source, drug,<br/>extracted, patient"]

    I --> J["LOG<br/>to_audit_record(decision)"]

    J --> K["dict / JSON<br/>timestamp, drug, status,<br/>reasons, rule_source,<br/>order_text, patient,<br/>audit_hash (SHA-256)"]

    K --> L["Caller's responsibility:<br/>persist this record somewhere durable<br/>(v0 does NOT do this itself - see FMEA row 7)"]

    style H4 fill:#fff3cd
    style L fill:#fff3cd
```

## What each stage does and doesn't do

| Stage | Input | Output | Does NOT do |
|---|---|---|---|
| **Extract** | Raw text | `list[ExtractedOrder]` | Never looks at `PatientInfo` - deliberately kept blind to patient data, see README's input-contract section |
| **Normalize** | `drug_canonical` string | `NormalizedDrug` or `None` | No fuzzy drug-concept matching beyond what Extract already resolved - a genuinely unrecognized drug simply isn't checked |
| **Check** (dispatch) | `ExtractedOrder` + `PatientInfo` | `Decision` | No cross-order reasoning - each `ExtractedOrder` is checked completely independently, even multiple orders from the same `check_order()` call |
| **Log** | `Decision` | `dict` (JSON-serializable) | Does not write anywhere - returns the record, storage is the caller's job |

## The one contract that constrains everything upstream
`check_order(text, patient)` assumes **exactly one patient** per call. This
isn't enforced by any type system - it's a documented contract (see
`check_order()`'s docstring and README). Nothing in this diagram can
detect a caller violating it; a multi-patient ward-round note passed in
one call will silently apply the single `patient` argument to every order
found, correctly for at most one of them.

## Extending this diagram
Adding drug #4 doesn't change this diagram's shape at all - it adds one
more branch under the CHECK dispatch box, registered in `_CHECKERS`
(see `engine.py`). If a new drug is added to `normalize.py`/`extract.py`
but its checker function isn't added to `_CHECKERS`, the "unregistered
drug" safety net branch (H4) fires automatically rather than the order
silently vanishing - this was a real gap in the dispatch design until v0.6.
