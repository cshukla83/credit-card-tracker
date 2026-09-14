from __future__ import annotations

from datetime import date, datetime
from typing import Callable, Optional, TypedDict

import pdfplumber


class Transaction(TypedDict):
    date: datetime
    description: str
    amount: float
    type: str  # "debit" or "credit"
    reward_points: Optional[int]
    # True only for a credit that is a payment *to* the card (the cardholder
    # paying the bill), never for a refund credit. Each bank's parser decides
    # this from its own statement text (Session 61); see is_payment_credit.
    is_payment: bool


def is_payment_credit(txn_type: str, description: str, prefixes: "tuple[str, ...]") -> bool:
    """Bank-agnostic helper for the per-bank rule: a credit whose description
    starts with one of the bank's known card-payment lead tokens.

    The prefixes themselves are owned by each bank's parser module -- that is
    where the statement-format knowledge lives -- so this only does the
    comparison: case-insensitive, leading whitespace ignored, nothing else
    normalised. A debit is never a payment, whatever its text says.
    """
    if txn_type != "credit":
        return False
    text = description.casefold().lstrip()
    return any(text.startswith(p.casefold()) for p in prefixes)


class ParsedStatement(TypedDict):
    period_start: date
    period_end: date
    transactions: "list[Transaction]"


# Every statement parser module exposes a function matching this signature:
#     def parse(pdf_path: str, password: str) -> ParsedStatement: ...
# The statement period is bank-agnostic (every credit card statement has one),
# so it lives in this shared return shape rather than being Diners-specific.
ParseFn = Callable[[str, str], ParsedStatement]


def extract_all_text(pdf_path: str, password: "str | None") -> "list[str]":
    """Every page's extract_text(), in order, empty string for a blank page.

    Shared by the parsers that read a statement as plain text rather than
    by layout (generic_fallback, llm_assist -- Sessions 99-100).
    """
    with pdfplumber.open(pdf_path, password=password) as pdf:
        return [page.extract_text() or "" for page in pdf.pages]
