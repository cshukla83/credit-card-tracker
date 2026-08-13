from __future__ import annotations

import re
from datetime import datetime

import pdfplumber

from parsers.base import Transaction

CREDIT_KEYWORDS = ("PAYMENT", "REFUND", "REVERSAL", "CASHBACK", "CREDIT")

_CURRENCY_RE = r"C\s*([\d,]+\.\d{2})"

# Matches one transaction line as it comes out of pdfplumber's extract_text(),
# e.g. "17/06/2026| 21:45 SOME MERCHANT C 216.00 l" or, when reward points were
# earned, "...SOME MERCHANT + 80 C 2,438.00 l". A lone "+" with no digits before
# the amount (no reward points earned that transaction) is also tolerated.
_TXN_LINE_RE = re.compile(
    r"^(?P<date>\d{2}/\d{2}/\d{4})\|\s*(?P<time>\d{2}:\d{2})\s+"
    r"(?P<desc>.*?)\s*"
    r"(?:\+\s*(?P<points>\d+)\s+)?"
    r"(?:\+\s+)?"
    r"C\s*(?P<amount>[\d,]+\.\d{2})\s+\S+\s*$"
)


def _to_float(amount_str: str) -> float:
    return float(amount_str.replace(",", ""))


def extract_summary(pdf_path: str, password: str) -> dict:
    """Pull the page-1 summary box's key totals, used to cross-check parsed transactions.

    Tailored to this statement's specific text-extraction layout, where the
    summary figures land on one line ending in "=" (previous dues, credits
    received, purchases/debit, finance charges, in that order) and the total
    amount due lands on a separate line starting with "_".
    """
    with pdfplumber.open(pdf_path, password=password) as pdf:
        text = pdf.pages[0].extract_text() or ""

    summary = {
        "total_amount_due": None,
        "previous_statement_dues": None,
        "payments_credits_received": None,
        "purchases_debit": None,
        "finance_charges": None,
    }

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("_") and "C" in stripped:
            match = re.search(_CURRENCY_RE, stripped)
            if match:
                summary["total_amount_due"] = _to_float(match.group(1))
        elif stripped.endswith("="):
            amounts = re.findall(_CURRENCY_RE, stripped)
            if len(amounts) >= 4:
                (
                    summary["previous_statement_dues"],
                    summary["payments_credits_received"],
                    summary["purchases_debit"],
                    summary["finance_charges"],
                ) = (_to_float(a) for a in amounts[:4])

    return summary


def _classify(description: str, amount: float, credits_received_total: float | None) -> str:
    upper_desc = description.upper()
    if any(keyword in upper_desc for keyword in CREDIT_KEYWORDS):
        return "credit"
    if credits_received_total is not None and abs(amount - credits_received_total) < 0.01:
        return "credit"
    return "debit"


def parse(pdf_path: str, password: str) -> "list[Transaction]":
    summary = extract_summary(pdf_path, password)
    credits_received_total = summary["payments_credits_received"]

    transactions: list[Transaction] = []

    with pdfplumber.open(pdf_path, password=password) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for line in text.splitlines():
                match = _TXN_LINE_RE.match(line.strip())
                if not match:
                    continue

                date = datetime.strptime(
                    f"{match.group('date')} {match.group('time')}", "%d/%m/%Y %H:%M"
                )
                description = match.group("desc").strip()
                amount = _to_float(match.group("amount"))
                points = match.group("points")

                transactions.append(
                    Transaction(
                        date=date,
                        description=description,
                        amount=amount,
                        type=_classify(description, amount, credits_received_total),
                        reward_points=int(points) if points else None,
                    )
                )

    return transactions
