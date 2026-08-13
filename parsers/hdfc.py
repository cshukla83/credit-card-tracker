from __future__ import annotations

import re
from datetime import datetime

import pdfplumber

from parsers import hdfc_legacy
from parsers.base import Transaction

CREDIT_KEYWORDS = ("PAYMENT", "REFUND", "REVERSAL", "CASHBACK", "CREDIT")

_CURRENCY_RE = r"C\s*([\d,]+\.\d{2})"

# Matches one transaction line as it comes out of pdfplumber's extract_text(),
# e.g. "17/06/2026| 21:45 SOME MERCHANT C 216.00 l" or, when reward points were
# earned, "...SOME MERCHANT + 80 C 2,438.00 l". Reward points can also be negative
# (points clawed back, e.g. on a merchant refund of a purchase that had earned
# points): "...SOME MERCHANT - 65 + C 216.00 l". A lone "+" with no digits before
# the amount is captured as credit_marker: in practice this bare "+" reliably
# marks non-purchase lines (payments, refunds) even when the description carries
# no recognizable keyword.
_TXN_LINE_RE = re.compile(
    r"^(?P<date>\d{2}/\d{2}/\d{4})\|\s*(?P<time>\d{2}:\d{2})\s+"
    r"(?P<desc>.*?)\s*"
    r"(?:(?P<points_sign>[+-])\s*(?P<points>\d+)\s+)?"
    r"(?:(?P<credit_marker>\+)\s+)?"
    r"C\s*(?P<amount>[\d,]+\.\d{2})\s+\S+\s*$"
)


def _to_float(amount_str: str) -> float:
    return float(amount_str.replace(",", ""))


def _extract_summary_current_layout(pdf_path: str, password: str) -> dict:
    """Pull the page-1 summary box's key totals, used to cross-check parsed transactions.

    Tailored to the current (2026-era) statement's text-extraction layout, where
    the summary figures land on one line ending in "=" (previous dues, credits
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


def _classify(
    description: str,
    amount: float,
    credits_received_total: float | None,
    has_credit_marker: bool,
) -> str:
    upper_desc = description.upper()
    if any(keyword in upper_desc for keyword in CREDIT_KEYWORDS):
        return "credit"
    if has_credit_marker:
        return "credit"
    if credits_received_total is not None and abs(amount - credits_received_total) < 0.01:
        return "credit"
    return "debit"


def _parse_current_layout(pdf_path: str, password: str) -> "list[Transaction]":
    summary = _extract_summary_current_layout(pdf_path, password)
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
                points_sign = match.group("points_sign")
                has_credit_marker = match.group("credit_marker") is not None

                reward_points = int(points) if points else None
                if reward_points is not None and points_sign == "-":
                    reward_points = -reward_points

                transactions.append(
                    Transaction(
                        date=date,
                        description=description,
                        amount=amount,
                        type=_classify(description, amount, credits_received_total, has_credit_marker),
                        reward_points=reward_points,
                    )
                )

    return transactions


def _detect_layout(pdf_path: str, password: str) -> str:
    """Sniff page 1 for a landmark string unique to each known HDFC statement layout.

    HDFC changed this statement's template at some point; older statements
    ("legacy") and newer ones ("current") need different parsing logic even
    though both are nominally "an HDFC Diners statement".
    """
    with pdfplumber.open(pdf_path, password=password) as pdf:
        text = pdf.pages[0].extract_text() or ""

    if "PAYMENTS/CREDITS" in text:
        return "current"
    if "Account Summary" in text:
        return "legacy"
    raise ValueError(f"Unrecognized HDFC statement layout: {pdf_path}")


def parse(pdf_path: str, password: str) -> "list[Transaction]":
    layout = _detect_layout(pdf_path, password)
    if layout == "legacy":
        return hdfc_legacy.parse(pdf_path, password)
    return _parse_current_layout(pdf_path, password)


def extract_summary(pdf_path: str, password: str) -> dict:
    layout = _detect_layout(pdf_path, password)
    if layout == "legacy":
        return hdfc_legacy.extract_summary(pdf_path, password)
    return _extract_summary_current_layout(pdf_path, password)
