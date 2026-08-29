from __future__ import annotations

import re
from datetime import date, datetime

import pdfplumber

from parsers.base import ParsedStatement, Transaction

# Matches one transaction line as it comes out of pdfplumber's extract_text(),
# e.g. "17/03/2026 13067759173 SOME MERCHANT BANGALORE IN 0 1,199.51" or, on a
# credit/refund row, "01/04/2026 13150014837 BBPS Payment received 0 2,860.00 CR".
# Reward points are a plain integer with no "+" prefix (unlike HDFC), and can be
# negative on a credit row where points were clawed back, e.g. "... IN -3 175.00
# CR". An optional international-amount field can appear between reward points
# and the final (INR) amount for foreign-currency transactions; the sample
# statement never exercised this column, so it's parsed defensively and
# discarded rather than left to break the match.
#
# Uses search() rather than match()/fullmatch(): on the sample statement's page
# 1, the pie-chart category-breakdown legend (e.g. "7% 31%") sometimes lands on
# the same physical text line as a real transaction, ahead of the date, because
# of how the chart and table overlap positionally in the PDF. Anchoring only at
# the end ("$") and not the start lets that leading noise be ignored rather than
# needing a separate strip step, while lines with no date anywhere (headers,
# category-only legend lines) still correctly fail to match at all.
#
# The serial/reference number is captured (it's structurally its own column,
# unlike HDFC where a reference number is just part of the description text)
# but intentionally not persisted: Transaction has no field for it, and there's
# no established reconciliation use for it yet.
_TXN_LINE_RE = re.compile(
    r"(?P<date>\d{2}/\d{2}/\d{4})\s+(?P<serno>\d+)\s+(?P<desc>.*?)\s+"
    r"(?P<points>-?\d+)\s+"
    r"(?:(?P<intl_amount>[\d,]+\.\d{2})\s+)?"
    r"(?P<amount>[\d,]+\.\d{2})"
    r"(?:\s+(?P<credit_marker>CR))?\s*$"
)

# e.g. "Statement period : March 17, 2026 to April 16, 2026" -- states the
# billing period directly, in "Month DD, YYYY" form on both sides, unlike the
# transaction lines' "DD/MM/YYYY" form.
_PERIOD_RE = re.compile(
    r"Statement period\s*:\s*(?P<start>[A-Za-z]+ \d{1,2}, \d{4})\s+to\s+"
    r"(?P<end>[A-Za-z]+ \d{1,2}, \d{4})"
)

# The page-1 reconciliation line, e.g.:
#   "Previous Balance Purchases / Charges Cash Advances Payments / Credits"
#   "`2,860.00 `18,400.71 `0.00 `3,035.00"
# The backtick is a font-encoding artifact standing in for the rupee symbol
# ("`" in extract_text() output where the PDF renders "₹"); amounts are
# matched with or without it. "Purchases / Charges" and "Payments / Credits"
# are the two totals a parsed statement's debit/credit sums should reconcile
# against.
_RECONCILIATION_RE = re.compile(
    r"Previous Balance\s+Purchases\s*/\s*Charges\s+Cash Advances\s+Payments\s*/\s*Credits\s*\n"
    r"\s*`?(?P<previous_balance>[\d,]+\.\d{2})\s+"
    r"`?(?P<purchases_charges>[\d,]+\.\d{2})\s+"
    r"`?(?P<cash_advances>[\d,]+\.\d{2})\s+"
    r"`?(?P<payments_credits>[\d,]+\.\d{2})"
)

_TOTAL_DUE_RE = re.compile(r"Total Amount due\s*\n\s*`?(?P<total>[\d,]+\.\d{2})")
_MIN_DUE_RE = re.compile(r"Minimum Amount due[^\n]*\n\s*`?(?P<min>[\d,]+\.\d{2})")


def _to_float(amount_str: str) -> float:
    return float(amount_str.replace(",", ""))


def _classify(has_credit_marker: bool) -> str:
    # Unlike HDFC, ICICI marks every credit/refund row with an explicit "CR"
    # suffix on the amount -- no keyword-matching or amount-equality fallback
    # is needed, the marker alone is a reliable signal for this layout.
    return "credit" if has_credit_marker else "debit"


def _parse_line(line: str) -> "Transaction | None":
    match = _TXN_LINE_RE.search(line.strip())
    if not match:
        return None

    txn_date = datetime.strptime(match.group("date"), "%d/%m/%Y")
    description = match.group("desc").strip()
    amount = _to_float(match.group("amount"))
    reward_points = int(match.group("points"))
    has_credit_marker = match.group("credit_marker") is not None

    return Transaction(
        date=txn_date,
        description=description,
        amount=amount,
        type=_classify(has_credit_marker),
        reward_points=reward_points,
    )


def _extract_period_from_text(text: str) -> "tuple[date | None, date | None]":
    match = _PERIOD_RE.search(text)
    if not match:
        return None, None
    period_start = datetime.strptime(match.group("start"), "%B %d, %Y").date()
    period_end = datetime.strptime(match.group("end"), "%B %d, %Y").date()
    return period_start, period_end


def _extract_summary_from_text(text: str) -> dict:
    summary = {
        "total_amount_due": None,
        "minimum_amount_due": None,
        "previous_balance": None,
        "purchases_charges": None,
        "cash_advances": None,
        "payments_credits": None,
    }

    total_match = _TOTAL_DUE_RE.search(text)
    if total_match:
        summary["total_amount_due"] = _to_float(total_match.group("total"))

    min_match = _MIN_DUE_RE.search(text)
    if min_match:
        summary["minimum_amount_due"] = _to_float(min_match.group("min"))

    reconciliation_match = _RECONCILIATION_RE.search(text)
    if reconciliation_match:
        summary["previous_balance"] = _to_float(reconciliation_match.group("previous_balance"))
        summary["purchases_charges"] = _to_float(reconciliation_match.group("purchases_charges"))
        summary["cash_advances"] = _to_float(reconciliation_match.group("cash_advances"))
        summary["payments_credits"] = _to_float(reconciliation_match.group("payments_credits"))

    return summary


def _parse_transactions(pdf_path: str, password: str) -> "list[Transaction]":
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

    with pdfplumber.open(pdf_path, password=password) as pdf:
        text = pdf.pages[0].extract_text() or ""
    period_start, period_end = _extract_period_from_text(text)

    return ParsedStatement(
        period_start=period_start,
        period_end=period_end,
        transactions=transactions,
    )
