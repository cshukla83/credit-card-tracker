from __future__ import annotations

import re
from datetime import date, datetime

import pdfplumber

from parsers.base import ParsedStatement, Transaction

_AMOUNT_RE = r"[\d,]+\.\d{2}"

# This layout never prints an explicit billing-period range (unlike the
# current layout's "Billing Period DD Mon, YYYY - DD Mon, YYYY" line) -- only
# a single closing "Statement Date". period_end comes from that; period_start
# is derived as the earliest parsed transaction date, which matches this
# statement's actual ~1-month billing cycle exactly (verified against real
# sample statements: min transaction date landed on the same day-of-month as
# the cycle start seen in current-layout statements, one month before
# period_end).
_STATEMENT_DATE_RE = re.compile(r"Statement Date:?\s*(\d{2}/\d{2}/\d{4})")

# Matches one transaction line from the pre-2025-layout HDFC statement's
# extract_text() output, e.g.:
#   "17/01/2025 17:50:36 FIRSTCRY PUNE 25 811.35"      (debit, reward points earned)
#   "18/01/2025 14:40:43 ZEPTO NOW MUMBAI 2,083.14"     (debit, no points)
#   "03/02/2025 05:05:15 TELE TRANSFER CREDIT (Ref# ...) 40,915.00Cr"  (credit)
# Unlike the current-layout statements, amounts here carry no currency-symbol
# prefix, time-of-day (when present) includes seconds, and credits are marked
# with a literal "Cr" suffix glued directly to the amount (no space) instead
# of an ambiguous "+" marker.
_TXN_LINE_RE = re.compile(
    r"^(?P<date>\d{2}/\d{2}/\d{4})\s+"
    r"(?:(?P<time>\d{2}:\d{2}:\d{2})\s+)?"
    r"(?P<desc>.*?)\s*"
    r"(?:(?P<points>\d+)\s+)?"
    rf"(?P<amount>{_AMOUNT_RE})(?P<credit_marker>Cr)?\s*$"
)


def _to_float(amount_str: str) -> float:
    return float(amount_str.replace(",", ""))


def _extract_summary_from_text(text: str) -> dict:
    """Pull the page-1 "Account Summary" box's key totals.

    Tailored to the pre-2025-layout statement, where these five figures
    (opening balance, payment/credits, purchase/debits, finance charges, total
    dues) appear together on one line of plain numbers, with no currency
    symbol or "=" anchor — located by finding a line of exactly 5
    amount-shaped tokens following the "Account Summary" section header.
    """
    summary = {
        "total_amount_due": None,
        "previous_statement_dues": None,
        "payments_credits_received": None,
        "purchases_debit": None,
        "finance_charges": None,
    }

    seen_header = False
    for line in text.splitlines():
        stripped = line.strip()
        if "Account Summary" in stripped:
            seen_header = True
            continue
        if not seen_header:
            continue

        tokens = stripped.split()
        if len(tokens) == 5 and all(re.fullmatch(_AMOUNT_RE, t) for t in tokens):
            (
                summary["previous_statement_dues"],
                summary["payments_credits_received"],
                summary["purchases_debit"],
                summary["finance_charges"],
                summary["total_amount_due"],
            ) = (_to_float(t) for t in tokens)
            break

    return summary


def _parse_line(line: str) -> "Transaction | None":
    match = _TXN_LINE_RE.match(line.strip())
    if not match:
        return None

    description = match.group("desc").strip()
    # Guards against summary/table rows that happen to start with a
    # date-shaped token followed by nothing but numbers (no real transaction
    # description ever lacks letters).
    if not any(c.isalpha() for c in description):
        return None

    time_str = match.group("time") or "00:00:00"
    date = datetime.strptime(f"{match.group('date')} {time_str}", "%d/%m/%Y %H:%M:%S")

    amount = _to_float(match.group("amount"))
    points = match.group("points")
    is_credit = match.group("credit_marker") is not None

    return Transaction(
        date=date,
        description=description,
        amount=amount,
        type="credit" if is_credit else "debit",
        reward_points=int(points) if points else None,
    )


def _extract_period_end_from_text(text: str) -> "date | None":
    match = _STATEMENT_DATE_RE.search(text)
    if not match:
        return None
    return datetime.strptime(match.group(1), "%d/%m/%Y").date()


def extract_summary(pdf_path: str, password: str) -> dict:
    with pdfplumber.open(pdf_path, password=password) as pdf:
        text = pdf.pages[0].extract_text() or ""
    return _extract_summary_from_text(text)


def parse(pdf_path: str, password: str) -> ParsedStatement:
    transactions: list[Transaction] = []

    with pdfplumber.open(pdf_path, password=password) as pdf:
        first_page_text = pdf.pages[0].extract_text() or ""
        for page in pdf.pages:
            text = page.extract_text() or ""
            for line in text.splitlines():
                transaction = _parse_line(line)
                if transaction is not None:
                    transactions.append(transaction)

    period_end = _extract_period_end_from_text(first_page_text)
    period_start = min((t["date"] for t in transactions), default=None)
    if period_start is not None:
        period_start = period_start.date()

    return ParsedStatement(
        period_start=period_start,
        period_end=period_end,
        transactions=transactions,
    )
