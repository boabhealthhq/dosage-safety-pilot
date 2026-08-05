# Security & Safety Issue Reporting

This project checks AI-generated clinical text for dosing errors. If you
find a way it could **miss a genuinely dangerous order, or incorrectly
clear one as safe**, that's a safety issue, not just a bug - please
report it responsibly rather than opening a public issue first.

## How to report
Email boabhealth@gmail.com with:
- The exact input text and patient data that triggered the problem
- What the tool did vs. what it should have done
- Whether you think this is a clinical threshold error (wrong number) or
  an extraction/logic error (right number, wrong code path)

## What happens next
This is a solo-maintained pilot, not a funded team with an SLA - please
allow a reasonable window for a response. Genuine safety findings will be
prioritized over anything else, including new feature work.

## Scope
This tool is a decision-support layer, not a certified medical device -
see the LICENSE file's clinical safety notice. It does not replace
independent clinical judgement. Known limitations are documented in
FMEA.md and the README's version history - check there first, since a
few real gaps (e.g. liquid concentration vs. administered dose confusion)
are already known and tracked, not hidden.
