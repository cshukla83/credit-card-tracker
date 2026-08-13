from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional, TypedDict


class Transaction(TypedDict):
    date: datetime
    description: str
    amount: float
    type: str  # "debit" or "credit"
    reward_points: Optional[int]


# Every statement parser module exposes a function matching this signature:
#     def parse(pdf_path: str, password: str) -> list[Transaction]: ...
ParseFn = Callable[[str, str], "list[Transaction]"]
