"""Reconciliation of a parsed statement against its own summary box (Session 98).

The rule every bank's real-statement test has applied since Session 8: the
parsed debit sum must equal the summary's purchases figure and the parsed
credit sum its payments/credits figure, each within a paisa (0.01). Both
sides are reported separately -- a mismatch on one side is a different
finding from a mismatch on the other, and collapsing them into one total
would hide which -- and the status is "match" only when both hold.

A side whose expected figure the summary extraction could not find is
reported with `expected: None` and the status is "unverified" (Session
114): the rows were read but there was nothing to check them against,
which is a different finding from "mismatch", where both figures exist
and disagree. Unverified is not verified -- the confirm gate treats it
exactly like a mismatch -- but the user is told which of the two they
are looking at. A registry bank parser always returns both figures, so
it never reports unverified; best_effort and llm_assist can.
"""

from __future__ import annotations

TOLERANCE = 0.01


def _side(parsed: float, expected: "float | None") -> dict:
    parsed = round(parsed, 2)
    if expected is None:
        return {"expected": None, "parsed": parsed, "delta": None}
    return {"expected": expected, "parsed": parsed, "delta": round(parsed - expected, 2)}


def _matches(side: dict) -> bool:
    return side["delta"] is not None and abs(side["delta"]) < TOLERANCE


def reconcile(
    transactions: "list[dict]", expected_debit: "float | None", expected_credit: "float | None"
) -> dict:
    debit = _side(sum(t["amount"] for t in transactions if t["type"] == "debit"), expected_debit)
    credit = _side(sum(t["amount"] for t in transactions if t["type"] == "credit"), expected_credit)
    if debit["expected"] is None or credit["expected"] is None:
        status = "unverified"
    elif _matches(debit) and _matches(credit):
        status = "match"
    else:
        status = "mismatch"
    return {"status": status, "debit": debit, "credit": credit}
