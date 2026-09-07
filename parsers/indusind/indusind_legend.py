from __future__ import annotations

import re
from datetime import date, datetime

import pdfplumber

from parsers.base import ParsedStatement, Transaction

# Matches one transaction line as it comes out of pdfplumber's extract_text(),
# e.g. "16/12/2025 SOME MERCHANT BENGALURU IN GROCERY & 10 986.00 DR" or, on a
# credit row, "27/12/2025 SOME PAYMENT PROCESSOR IN -17 871.06 CR".
#
# Columns are: date | transaction details | merchant category | reward points |
# amount | DR/CR marker.
#
# NOT anchored at the end ("$"), and this is the single most important thing
# about this regex. The statement's page-1 summary box is a right-hand SIDEBAR
# that pdfplumber's text extraction merges into the main text flow, so sidebar
# labels and values land appended to the END of whatever transaction row sits
# at the same vertical position, e.g.:
#
#   "16/12/2025 SOME MERCHANT ... 10 986.00 DR Total Outstanding"
#   "16/12/2025 SOME MERCHANT ... 6 618.00 DR 5,302.11 DR"
#
# The second form is the dangerous one: the line ends with a SECOND
# amount/marker pair belonging to the sidebar, not to the transaction. Anchoring
# at the end would either reject these rows outright (two of the five debit rows
# in the primary sample -- reconciliation would then fail loudly, which is at
# least safe) or, with a greedy description, silently capture the sidebar's
# amount instead of the transaction's, which would NOT fail loudly. Leaving the
# tail unanchored and making the description lazy makes the match LEFTMOST, so
# the first points/amount/marker triple after the date wins -- which is always
# the real transaction. This is the same hazard ICICI presented (chart legend
# text merging into transaction rows), mirrored to the trailing side.
#
# The trailing "(?:\s|$)" stops "DR"/"CR" from matching a longer token's prefix.
#
# The marker is captured loosely as [A-Z]{2,4} rather than as (DR|CR) on
# purpose. A strict alternation would make an unrecognized marker fail to match
# at all, and the row would be silently DROPPED -- the exact silent-miss failure
# the unknown-marker rule exists to prevent. Capturing loosely and validating in
# _classify() turns an unfamiliar marker into a loud error instead.
_TXN_LINE_RE = re.compile(
    r"^(?P<date>\d{2}/\d{2}/\d{4})\s+"
    r"(?P<desc>.*?)\s+"
    r"(?P<points>-?\d+)\s+"
    r"(?P<amount>[\d,]+\.\d{2})\s+"
    r"(?P<marker>[A-Z]{2,4})(?:\s|$)"
)

# The billing period, e.g. "16/12/2025 To 15/01/2026". It sits in the sidebar
# under a "Statement Period" label, but the label and value are separated by
# unrelated interleaved lines, so keying off the label's line offset would be
# fragile. Two dates joined by "To" is distinctive enough to match directly, and
# it occurs exactly once per statement in all four samples -- verified rather
# than assumed.
_PERIOD_RE = re.compile(r"(?P<start>\d{2}/\d{2}/\d{4})\s+To\s+(?P<end>\d{2}/\d{2}/\d{4})")

# Section headers inside the transaction table, e.g.
# "Payment Details for MR SOME NAME (Credit Card No. 4147XXXXXXXX9015)" and
# "Purchases & Cash Transactions for MR SOME NAME (Credit Card No. ...)".
# They split the table into a credits section and a debits section, per
# cardholder.
#
# TODO: cardholder attribution is dropped, matching the SBI parser's treatment.
# Transaction has no field for it and storage/ has no column, so which
# cardholder made a spend is lost on import. The information IS recoverable from
# these headers if per-cardholder breakdowns are ever wanted.
_SECTION_HEADER_RE = re.compile(r"^(?:Payment Details|Purchases & Cash Transactions)\s+for\b")

# Per-section subtotal rows, e.g. "Total 62 6,173.12" / "Total -17 19,809.06".
# They carry a points total and an amount but no date and no DR/CR marker, so
# the date-anchored regex rejects them anyway. Checked explicitly so the skip is
# intentional and testable rather than incidental -- and so that a future layout
# that started dating its subtotals could not quietly double-count them into the
# transaction list.
_SUBTOTAL_RE = re.compile(r"^Total\b")

# DR/CR markers. IndusInd prints one on EVERY row -- unlike ICICI, where the
# absence of a "CR" suffix is what implies a debit. An explicit marker on both
# sides means there is no "assume debit" default to fall back on, and none is
# provided: an unrecognized marker raises.
_MARKER_TO_TYPE = {
    "DR": "debit",
    "CR": "credit",
}

# Summary-box fields. Each label sits alone on its own line with the value on
# the line IMMEDIATELY FOLLOWING it -- genuinely adjacent, unlike the SBI
# statement where labels and values were separated and had to be matched by
# validated column order. Because the box is a sidebar, the value line may carry
# unrelated left-column text merged in front of it (e.g. the credit-limit header
# row), so the value taken is the LAST amount on that line, not the only one.
#
# "Minimum Amount Due" is matched with an end-of-line anchor because the phrase
# also opens a prose paragraph elsewhere on page 1 ("Minimum Amount Due (MAD)
# calculation on your ..."); without the anchor that paragraph would win.
#
# Total Amount Due is deliberately NOT extracted. Its value lands at the end of
# an unrelated prose line two rows below its label, with no structural
# relationship to it -- an offset that holds across all four samples but is
# brittle by construction. It is not needed for reconciliation, so extracting it
# would add a silent-breakage surface for no benefit. Total Outstanding is
# omitted for the same reason.
_SUMMARY_LABELS = {
    "previous_balance": r"Previous Balance",
    "purchases_charges": r"Purchases & Other Charges",
    "cash_advance": r"Cash Advance",
    "payments_credits": r"Payment & Other Credits",
    "minimum_amount_due": r"Minimum Amount Due",
}

_AMOUNT_RE = re.compile(r"[\d,]+\.\d{2}")


def _to_float(amount_str: str) -> float:
    return float(amount_str.replace(",", ""))


def _classify(marker: str) -> str:
    """Map a DR/CR marker to "debit" or "credit".

    Raises ValueError on an unrecognized marker rather than defaulting: a
    wrong-sided transaction breaks reconciliation with no visible error, which
    is the hardest class of bug to notice after import.
    """
    try:
        return _MARKER_TO_TYPE[marker]
    except KeyError:
        raise ValueError(
            f"unknown IndusInd transaction marker {marker!r} "
            f"(known markers: {', '.join(sorted(_MARKER_TO_TYPE))})"
        ) from None


def _parse_line(line: str) -> "Transaction | None":
    """Parse one text line into a Transaction, or None if it isn't one.

    Returns None for section headers, subtotal rows, and wrapped-description
    continuation lines. When a merchant category is too long for its column it
    wraps onto a following line carrying only the category tail (and possibly
    some merged sidebar text); those lines have no leading date and are skipped.
    A consequence is that the captured description keeps whatever category
    fragment shared the date's line and loses the wrapped remainder -- cosmetic
    only, since amount, sign, points and date all live on the dated line.
    """
    stripped = line.strip()

    if _SECTION_HEADER_RE.match(stripped) or _SUBTOTAL_RE.match(stripped):
        return None

    match = _TXN_LINE_RE.match(stripped)
    if not match:
        return None

    return Transaction(
        date=datetime.strptime(match.group("date"), "%d/%m/%Y"),
        description=match.group("desc").strip(),
        amount=_to_float(match.group("amount")),
        type=_classify(match.group("marker")),
        # IndusInd DOES report points per transaction (like ICICI, unlike SBI).
        # They can be zero, or negative where points are clawed back on a
        # refund/credit row.
        reward_points=int(match.group("points")),
    )


def _extract_period_from_text(text: str) -> "tuple[date | None, date | None]":
    match = _PERIOD_RE.search(text)
    if not match:
        return None, None
    period_start = datetime.strptime(match.group("start"), "%d/%m/%Y").date()
    period_end = datetime.strptime(match.group("end"), "%d/%m/%Y").date()
    return period_start, period_end


def _extract_summary_from_text(text: str) -> dict:
    summary = {key: None for key in _SUMMARY_LABELS}

    for key, label in _SUMMARY_LABELS.items():
        # Label alone on its line, value on the next line. Anchoring the label
        # at both ends is what makes a renamed or reordered label fail to match
        # (leaving the field None) rather than silently pairing a value with
        # the wrong name.
        match = re.search(rf"^{label}\s*$\n(?P<value_line>[^\n]*)$", text, re.MULTILINE)
        if not match:
            continue
        amounts = _AMOUNT_RE.findall(match.group("value_line"))
        if amounts:
            summary[key] = _to_float(amounts[-1])

    return summary


def _parse_transactions(pdf_path: str, password: str) -> "list[Transaction]":
    """Collect transactions from every page.

    In all four samples the transaction table fits on page 1 and the remaining
    pages are boilerplate (promotional messages, terms and conditions) with no
    date-anchored, marker-terminated lines. Every page is scanned regardless --
    both SBI and ICICI turned out to have samples that spill onto a later page,
    so assuming page 1 is a bet this codebase has already lost twice.
    """
    transactions: list[Transaction] = []

    with pdfplumber.open(pdf_path, password=password) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for line in text.splitlines():
                transaction = _parse_line(line)
                if transaction is not None:
                    transactions.append(transaction)

    return transactions


def extract_summary(pdf_path: str, password: str) -> dict:
    with pdfplumber.open(pdf_path, password=password) as pdf:
        text = pdf.pages[0].extract_text() or ""
    return _extract_summary_from_text(text)


def parse(pdf_path: str, password: str) -> ParsedStatement:
    transactions = _parse_transactions(pdf_path, password)

    period_start = period_end = None
    with pdfplumber.open(pdf_path, password=password) as pdf:
        for page in pdf.pages:
            period_start, period_end = _extract_period_from_text(page.extract_text() or "")
            if period_start is not None:
                break

    return ParsedStatement(
        period_start=period_start,
        period_end=period_end,
        transactions=transactions,
    )
