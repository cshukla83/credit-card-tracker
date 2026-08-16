from __future__ import annotations

from datetime import date, datetime
from typing import Callable, Optional, TypedDict


class Transaction(TypedDict):
    date: datetime
    description: str
    amount: float
    type: str  # "debit" or "credit"
    reward_points: Optional[int]


class ParsedStatement(TypedDict):
    period_start: date
    period_end: date
    transactions: "list[Transaction]"


# Every statement parser module exposes a function matching this signature:
#     def parse(pdf_path: str, password: str) -> ParsedStatement: ...
# The statement period is bank-agnostic (every credit card statement has one),
# so it lives in this shared return shape rather than being Diners-specific.
ParseFn = Callable[[str, str], ParsedStatement]
