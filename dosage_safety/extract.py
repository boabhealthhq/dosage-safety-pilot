"""
Extract step.

Job: find drug-order mentions in AI-generated clinical text and pull out
drug name + dose + unit + frequency + route. Nothing else.

Deliberately does NOT look for patient age/weight/height/sex here - those
arrive as a separate structured PatientInfo object (see models.py + README).

v0.2 rewrite - fixes found by stress-testing against messy, realistic text:
1. Orders split across multiple lines were silently losing their dose
   (segment splitting on newlines separated the drug name from its dose).
2. Two drugs mentioned in one unpunctuated sentence could have their
   dose/frequency silently swapped between them.
3. "q.i.d." (with periods) broke on the internal periods.
4. Decimal doses (e.g. "2.5g") were at risk of the same period problem.
5. Dose ranges ("500-1000mg") silently kept only the upper number with no
   record that a range was ever given.
6. Common real-world shorthand ("PCM") and single-character typos
   ("paracetmol") were silently invisible - no flag, no log entry, nothing.

Fix for (1) and (2) together: instead of pre-splitting text into segments
and searching each in isolation, find every drug-alias position in the
*whole* text first, then look forward from each one only as far as the
next drug alias or the next real sentence break - never past either. This
naturally spans line breaks (fixing 1) and naturally stops before it can
pick up a different drug's numbers (fixing 2).
"""

import re

from .models import ExtractedOrder

# v0: paracetamol only. Add new aliases here as new drugs are added to the rulebook.
# "pcm" added as a common real-world shorthand, not a typo - kept separate from
# the fuzzy-typo mechanism below.
DRUG_ALIASES = {
    "paracetamol": [
        "paracetamol", "panadol", "panamax", "dymadon",
        "acetaminophen", "tylenol", "apap", "pcm",
    ],
    "ibuprofen": [
        "ibuprofen", "nurofen", "brufen", "advil", "motrin", "ibu",
    ],
    "amoxicillin": [
        "amoxicillin", "amoxil", "moxatag", "amoxycillin",
    ],
    "loratadine": [
        "loratadine", "claritin",
    ],
    "dexamethasone": [
        "dexamethasone", "decadron", "dex",
    ],
    "fentanyl": [
        "fentanyl",
    ],
    "oxycodone": [
        "oxycodone", "oxycontin", "roxicodone", "endone",
    ],
}

# Matches a number with OR without comma thousand-separators - e.g. "500",
# "5000", "1,000", "12,500" all match correctly with no digits lost. The
# naive fix (just allowing commas anywhere) would have broken plain
# uncommaed 4+ digit numbers like "5000" - which matters a lot here, since
# those are exactly the large, dangerous doses this tool most needs to
# catch correctly, not the ones to risk truncating.
_NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"

# Unit alternation - ORDER MATTERS: longer/more specific patterns must come
# before their shorter prefixes (e.g. "mg/kg/day" before "mg/kg"), since
# regex alternation takes the first alternative that matches, not the
# longest. The "/day" variants mark an explicitly-stated DAILY TOTAL rather
# than a per-dose figure - found via independent evaluation to be a real,
# repeated source of dangerous misreads (e.g. "90mg/kg/day divided BD" was
# being read as 90mg/kg PER DOSE, doubling the real rate).
_UNIT_PATTERN = r"(mg/kg/day|mg/kg/24h|mg/kg|mg/day|mg|g/day|g|mcg/kg/day|mcg/kg|mcg)"

# Single-value dose, e.g. "500mg", "15mg/kg", "1,000mg", "90mg/kg/day"
DOSE_RE = re.compile(
    rf"({_NUMBER})\s*{_UNIT_PATTERN}\b", re.IGNORECASE
)

# Range dose, e.g. "500-1000mg" - checked BEFORE the single-value pattern
DOSE_RANGE_RE = re.compile(
    rf"({_NUMBER})\s*-\s*({_NUMBER})\s*{_UNIT_PATTERN}\b", re.IGNORECASE
)

# "divided" phrasing (e.g. "40mg/kg divided q8h") is a second, less explicit
# way of stating a daily total rather than a per-dose figure - same
# underlying issue as the "/day" units above, different wording.
DIVIDED_RE = re.compile(r"\bdivided\b", re.IGNORECASE)

INTERVAL_RE = re.compile(
    r"(\d+)\s*(?:-|to)?\s*(\d+)?\s*hourly"
    r"|q(\d+)(?:-(\d+))?h"
    r"|every\s+(\d+)\s*(?:-|to)?\s*(\d+)?\s*hours?",
    re.IGNORECASE,
)

# Minute-scale intervals - needed for opioid redosing instructions
# ("q5min", "every 10 minutes"), which the hour-only pattern above can't
# express. Converted to fractional hours for storage, since
# interval_low_hr/high_hr are always in hours.
MINUTE_INTERVAL_RE = re.compile(
    r"q(\d+)\s*min(?:ute)?s?\b"
    r"|every\s+(\d+)\s*min(?:ute)?s?\b",
    re.IGNORECASE,
)

ABBREV_INTERVALS = {
    "qid": (6, 6), "tds": (8, 8), "tid": (8, 8),
    "bd": (12, 12), "bid": (12, 12),
}
# "od" and "daily" are checked separately, and only as a fallback AFTER an
# explicit numeric interval has been tried - "daily" in particular shows up
# inside other phrases ("divided daily dose", "total daily amount") where
# it does NOT mean "once a day", and was found to shadow an explicit "q6h"
# stated elsewhere in the same order.
AMBIGUOUS_ABBREV_INTERVALS = {
    "od": (24, 24), "daily": (24, 24),
}

# Spelled-out frequency phrases ("three times a day", "twice daily") -
# found by independent evaluation to cause real dangerous misses, since
# only numeric/abbreviated forms had been tested before. Checked against
# the DIGIT form, after word-number normalization has already run.
_TIMES_PER_DAY_RE = re.compile(
    r"\b(\d+)\s*times?\s*(?:a\s+|per\s+)?(?:day|daily)\b", re.IGNORECASE
)
_SPECIAL_FREQUENCY_WORDS = [
    (re.compile(r"\bonce\s+(?:a\s+|per\s+)?(?:day|daily)\b", re.IGNORECASE), (24, 24)),
    (re.compile(r"\btwice\s+(?:a\s+|per\s+)?(?:day|daily)\b", re.IGNORECASE), (12, 12)),
    (re.compile(r"\bthrice\s+(?:a\s+|per\s+)?(?:day|daily)\b", re.IGNORECASE), (8, 8)),
]

# Dotted clinical shorthand (q.i.d., t.i.d. etc.) normalized to the plain
# form above BEFORE anything else runs, so periods inside an abbreviation
# never get mistaken for a sentence break. Longer patterns listed first so
# e.g. "t.i.d." isn't partially matched by a shorter, unrelated pattern.
_DOTTED_ABBREVS = [
    (re.compile(r"\bq\.i\.d\.?", re.IGNORECASE), "qid"),
    (re.compile(r"\bt\.i\.d\.?", re.IGNORECASE), "tid"),
    (re.compile(r"\bb\.i\.d\.?", re.IGNORECASE), "bid"),
    (re.compile(r"\bp\.r\.n\.?", re.IGNORECASE), "prn"),
    (re.compile(r"\bq\.d\.?", re.IGNORECASE), "od"),
    (re.compile(r"\bo\.d\.?", re.IGNORECASE), "od"),
]

# Spelled-out numbers, for interval phrases like "every four hours" -
# found by independent evaluation to cause real dangerous misses, since
# every prior stress-test round used numeric or abbreviated forms only.
_WORD_NUMBERS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
    "eleven": "11", "twelve": "12",
}
_WORD_NUMBER_RE = re.compile(r"\b(" + "|".join(_WORD_NUMBERS.keys()) + r")\b", re.IGNORECASE)
_TWENTY_FOUR_RE = re.compile(r"\btwenty[\s-]?four\b", re.IGNORECASE)

# "20mg per kilo" / "20mg per kg" -> normalized to "20mg/kg" so the existing
# dose regex can read it. A second real gap found by independent evaluation.
_PER_KG_RE = re.compile(
    rf"({_NUMBER})\s*mg\s+per\s*(?:kilo(?:gram)?|kg)\b", re.IGNORECASE
)

# Spelled-out units ("1 gram" instead of "1g") - a third real gap found by
# independent evaluation. Order-safe due to \b word boundaries: "grams"
# inside "milligrams" has no boundary before it, so won't be double-matched.
_UNIT_WORDS = [
    (re.compile(r"\bmilligrams?\b", re.IGNORECASE), "mg"),
    (re.compile(r"\bmicrograms?\b", re.IGNORECASE), "mcg"),
    (re.compile(r"\bgrams?\b", re.IGNORECASE), "g"),
]

# "divided into two doses" (no explicit interval unit) - treated as an
# interval-equivalent phrase, same idea as "twice daily".
_DIVIDED_INTO_N_RE = re.compile(r"\bdivided\s+into\s+(\d+)\s+doses?\b", re.IGNORECASE)

ROUTE_RE = re.compile(r"\b(PO|IV|IM|PR|SL|SC|subcut)\b", re.IGNORECASE)
# Deliberately case-SENSITIVE, unlike the other routes above: lowercase
# "in" is extremely common ordinary English ("given in the ED", "increase
# in dose") and would cause frequent false route captures if matched
# case-insensitively. Uppercase "IN" as a route abbreviation is a much
# safer signal.
INTRANASAL_ROUTE_RE = re.compile(r"\bIN\b")
PRN_RE = re.compile(r"\bPRN\b", re.IGNORECASE)

# A window-ending "sentence break": . ; or ! - but NOT when it's a decimal
# point (digit immediately before AND after), so "2.5g" is never mistaken
# for two sentences.
TERMINATOR_RE = re.compile(r"(?<!\d)[.;!](?!\d)")

# Fuzzy typo tolerance only applies to aliases at least this long, and only
# allows a single-character edit - short words are too risky to fuzzy-match
# (too easy to collide with an unrelated common word).
MIN_FUZZY_ALIAS_LEN = 5
MAX_FUZZY_EDIT_DISTANCE = 1


def _normalize_dotted_abbrevs(text: str) -> str:
    for pattern, replacement in _DOTTED_ABBREVS:
        text = pattern.sub(replacement, text)
    return text


def _normalize_word_numbers(text: str) -> str:
    text = _TWENTY_FOUR_RE.sub("24", text)
    return _WORD_NUMBER_RE.sub(lambda m: _WORD_NUMBERS[m.group(1).lower()], text)


def _normalize_per_kg_phrasing(text: str) -> str:
    return _PER_KG_RE.sub(lambda m: f"{m.group(1)}mg/kg", text)


def _normalize_unit_words(text: str) -> str:
    for pattern, replacement in _UNIT_WORDS:
        text = pattern.sub(replacement, text)
    return text


def _levenshtein(a: str, b: str) -> int:
    """Standard edit distance - how many single-character edits turn a into b."""
    if a == b:
        return 0
    m, n = len(a), len(b)
    if m == 0:
        return n
    if n == 0:
        return m
    prev = list(range(n + 1))
    for i in range(1, m + 1):
        curr = [i] + [0] * n
        for j in range(1, n + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[n]


def _find_all_alias_hits(text: str):
    """Find every drug-alias occurrence in the whole text, exact match first.
    Returns a list of (start, end, canonical, matched_text, is_fuzzy),
    sorted by position. Falls back to single-character-typo tolerance only
    for words with no exact match anywhere, so a real typo doesn't go
    completely unseen - but always comes back flagged as fuzzy, never
    silently treated as certain."""
    hits = []
    low = text.lower()

    for canonical, aliases in DRUG_ALIASES.items():
        for alias in aliases:
            for m in re.finditer(rf"\b{re.escape(alias)}\b", low):
                hits.append((m.start(), m.end(), canonical, text[m.start():m.end()], False))

    exact_spans = {(h[0], h[1]) for h in hits}

    # Fuzzy fallback: only consider words that didn't already get an exact hit
    for m in re.finditer(r"\b[a-zA-Z]+\b", low):
        start, end = m.start(), m.end()
        if any(start < e and end > s for s, e in exact_spans):
            continue  # overlaps a real match, skip
        word = low[start:end]
        if len(word) < MIN_FUZZY_ALIAS_LEN:
            continue
        for canonical, aliases in DRUG_ALIASES.items():
            for alias in aliases:
                if len(alias) < MIN_FUZZY_ALIAS_LEN:
                    continue  # too short to fuzzy-match safely
                if abs(len(word) - len(alias)) > MAX_FUZZY_EDIT_DISTANCE:
                    continue
                if _levenshtein(word, alias) == MAX_FUZZY_EDIT_DISTANCE:
                    hits.append((start, end, canonical, text[start:end], True))
                    break

    hits.sort(key=lambda h: h[0])
    return hits


def _search_dose(text_span: str):
    """Try the range pattern first, then the single-value pattern. Returns
    (kind, match) where kind is 'range' or 'single', or None if neither matched."""
    m = DOSE_RANGE_RE.search(text_span)
    if m:
        return ("range", m)
    m = DOSE_RE.search(text_span)
    if m:
        return ("single", m)
    return None


def extract_orders(text: str) -> list[ExtractedOrder]:
    """For every drug-alias occurrence in the text, look both forward and
    backward - bounded by the next/previous drug alias or the nearest real
    sentence break, whichever is closer - and pull the dose from whichever
    direction has the closer match. Handles both "paracetamol 500mg" and
    "500mg of paracetamol" phrasing. Interval/route/PRN are still read
    forward-only, since no case has yet shown a need to search backward
    for those. Never crosses into a different drug's numbers, and never
    stops at a bare line break within the same order."""
    text = _normalize_dotted_abbrevs(text)
    text = _normalize_word_numbers(text)
    text = _normalize_per_kg_phrasing(text)
    text = _normalize_unit_words(text)
    hits = _find_all_alias_hits(text)
    results = []

    for i, (start, end, canonical, alias_text, is_fuzzy) in enumerate(hits):
        window_end = len(text)
        if i + 1 < len(hits):
            window_end = min(window_end, hits[i + 1][0])

        term_match = TERMINATOR_RE.search(text, end, window_end)
        if term_match:
            window_end = term_match.start()

        # Backward bound: end of the previous alias, or the nearest
        # preceding sentence terminator - whichever is closer (later).
        back_bound = 0
        if i > 0:
            back_bound = hits[i - 1][1]
        last_back_term = None
        for tm in TERMINATOR_RE.finditer(text, back_bound, start):
            last_back_term = tm
        found_real_terminator = last_back_term is not None
        if last_back_term:
            back_bound = max(back_bound, last_back_term.end())

        # Only search backward when this is the FIRST alias in the text
        # (nothing before it to conflict with) or a real terminator
        # separates this order from the previous alias's own territory.
        # Without one, the gap between two consecutive aliases belongs to
        # the PREVIOUS alias's forward search - letting this alias's
        # backward search reach into it risks stealing the previous drug's
        # dose. Confirmed as a real bug: in "fentanyl 1.5mcg/kg IN and
        # oxycodone 0.1mg/kg...", oxycodone's backward search was pulling
        # in fentanyl's own dose from the shared, unpunctuated gap.
        allow_backward_search = (i == 0) or found_real_terminator
        backward_span = text[back_bound:start] if allow_backward_search else ""
        forward_span = text[start:window_end]

        back_result = _search_dose(backward_span) if backward_span else None
        fwd_result = _search_dose(forward_span)

        use_backward = False
        if back_result and fwd_result:
            back_distance = len(backward_span) - back_result[1].end()
            fwd_distance = fwd_result[1].start()
            use_backward = back_distance < fwd_distance
        elif back_result and not fwd_result:
            use_backward = True

        if use_backward:
            window = text[back_bound:window_end]
        else:
            window = text[start:window_end]
        clean_window = re.sub(r"\s+", " ", window).strip()
        # interval/route/PRN stay forward-only regardless of which
        # direction the dose was found in - no case has shown a need to
        # search backward for these, and doing so unconditionally would
        # risk picking up an unrelated interval mentioned before this order.
        forward_clean = re.sub(r"\s+", " ", forward_span).strip()

        range_match = DOSE_RANGE_RE.search(clean_window)
        dose_value = None
        dose_unit = None
        dose_is_range = False
        dose_range_low = None
        if range_match:
            dose_range_low = float(range_match.group(1).replace(",", ""))
            dose_value = float(range_match.group(2).replace(",", ""))  # conservative: use the upper bound
            dose_unit = range_match.group(3).lower()
            dose_is_range = True
        else:
            dose_match = DOSE_RE.search(clean_window)
            if dose_match:
                dose_value = float(dose_match.group(1).replace(",", ""))
                dose_unit = dose_match.group(2).lower()

        # Daily-total detection: either an explicit "/day" unit (e.g.
        # "90mg/kg/day") or the word "divided" nearby (e.g. "40mg/kg divided
        # q8h") both mean the extracted number is a DAILY total, not a
        # per-dose figure - the engine needs to know this to avoid reading
        # it as (much larger) per-dose amount. The "/day" suffix is then
        # stripped so downstream mg/g conversion logic doesn't need to
        # know about it separately.
        dose_is_daily_total = False
        if dose_unit and dose_unit.endswith("/day"):
            dose_unit = dose_unit[:-4]
            dose_is_daily_total = True
        elif dose_value is not None and DIVIDED_RE.search(clean_window):
            dose_is_daily_total = True

        lo, hi = _parse_interval(forward_clean)
        route_match = ROUTE_RE.search(forward_clean)
        if route_match:
            route = route_match.group(1).upper()
        else:
            intranasal_match = INTRANASAL_ROUTE_RE.search(forward_clean)
            route = "IN" if intranasal_match else None
        prn = bool(PRN_RE.search(forward_clean))

        results.append(
            ExtractedOrder(
                raw_segment=clean_window,
                drug_name_raw=alias_text,
                drug_canonical=canonical,
                dose_value=dose_value,
                dose_unit=dose_unit,
                interval_low_hr=lo,
                interval_high_hr=hi,
                route=route,
                prn=prn,
                is_fuzzy_match=is_fuzzy,
                dose_is_range=dose_is_range,
                dose_range_low=dose_range_low,
                dose_is_daily_total=dose_is_daily_total,
            )
        )

    return results


def _parse_interval(segment: str):
    low = segment.lower()

    for pattern, (lo, hi) in _SPECIAL_FREQUENCY_WORDS:
        if pattern.search(low):
            return lo, hi

    times_match = _TIMES_PER_DAY_RE.search(low)
    if times_match:
        n = int(times_match.group(1))
        if n > 0:
            interval = 24 / n
            return interval, interval

    divided_into_match = _DIVIDED_INTO_N_RE.search(low)
    if divided_into_match:
        n = int(divided_into_match.group(1))
        if n > 0:
            interval = 24 / n
            return interval, interval

    minute_match = MINUTE_INTERVAL_RE.search(low)
    if minute_match:
        minutes = int(minute_match.group(1) or minute_match.group(2))
        if minutes > 0:
            interval_hr = minutes / 60
            return interval_hr, interval_hr

    for word, (lo, hi) in ABBREV_INTERVALS.items():
        if re.search(rf"\b{word}\b", low):
            return lo, hi

    m = INTERVAL_RE.search(segment)
    if m:
        nums = [g for g in m.groups() if g is not None]
        if nums:
            if len(nums) == 1:
                v = float(nums[0])
                return v, v
            return float(nums[0]), float(nums[1])

    # Ambiguous fallback - checked LAST, only if nothing more explicit
    # matched. "daily"/"od" often appear inside other phrases ("total daily
    # dose") where they don't literally mean "once a day".
    for word, (lo, hi) in AMBIGUOUS_ABBREV_INTERVALS.items():
        if re.search(rf"\b{word}\b", low):
            return lo, hi

    return None, None
