"""Best-attempt, bank-agnostic statement parser (Session 99).

For a PDF no registry landmark recognises. It knows nothing about any bank's
layout; it reads each line of text as "a date, then a description, then an
amount, maybe a short flag" and keeps what fits. Same ParsedStatement
contract as every hand-built parser, so it flows through the same
preview / reconciliation / confirm path with no special casing -- and it is
expected to reconcile less often than they do. The reconciliation gate
(blocked by default, explicit override) is the safety net; nothing here
tries to be clever enough not to need it.

Heuristics, all deliberately generic:

  date        one of a handful of common shapes at the start of the line
              (DD/MM/YYYY, DD-MM-YYYY, YYYY-MM-DD, DD Mon YY, DD Mon YYYY,
              DD Mon, YYYY). A line has to carry a year to be a transaction;
              day-and-month-only rows are skipped rather than guessed.
  amount      the LAST "1,234.56"-shaped number on the line, so any points,
              serial numbers or foreign-currency amounts before it stay in
              the description rather than being taken for the amount.
  description everything between, with a leading clock time and a trailing
              currency marker (C, Rs, INR, a rupee symbol or the backtick
              some fonts emit for it) trimmed off; must contain a letter.
  type        credit when the flag after the amount is C / CR, when a bare
              "+" sits right before the amount, or when the description
              carries a credit keyword (payment, refund, reversal, cashback,
              credit) as a whole word; otherwise debit.
  is_payment  a credit whose description says PAYMENT and not REFUND -- a
              guess, editable on the review screen like any other row.
  period      "Statement/Billing Period <date> to/- <date>" anywhere in the
              text; failing that, the earliest and latest transaction dates.
  summary     a line whose label says purchases/debits, or payments/credits,
              followed by an amount on the same line. Most layouts put the
              labels and figures on different lines, so this usually finds
              nothing -- and a missing figure is reported as a mismatch,
              never as a match.
"""

from __future__ import annotations

import re
from datetime import date, datetime

import pdfplumber

from parsers.base import ParsedStatement, Transaction

# (regex, strptime format). Order matters only for the alternation below.
_DATE_SHAPES = [
    (r"\d{2}/\d{2}/\d{4}", "%d/%m/%Y"),
    (r"\d{2}-\d{2}-\d{4}", "%d-%m-%Y"),
    (r"\d{4}-\d{2}-\d{2}", "%Y-%m-%d"),
    (r"\d{1,2} [A-Za-z]{3}, \d{4}", "%d %b, %Y"),
    (r"\d{2} [A-Za-z]{3} \d{4}", "%d %b %Y"),
    (r"\d{2} [A-Za-z]{3} \d{2}", "%d %b %y"),
    (r"[A-Za-z]{3,9} \d{1,2}, \d{4}", "%B %d, %Y"),
]
_ANY_DATE = "(?:" + "|".join(shape for shape, _ in _DATE_SHAPES) + ")"
_AMOUNT = r"\d[\d,]*\.\d{2}"

_LINE_RE = re.compile(rf"^(?P<date>{_ANY_DATE})[|,]?\s+(?P<rest>.*\S)\s*$")
_AMOUNT_RE = re.compile(_AMOUNT)
_TIME_RE = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?\s*")
_CURRENCY_TAIL_RE = re.compile(r"\s*(?:C|Rs\.?|INR|₹|`)\s*$")
_CREDIT_FLAGS = {"C", "CR"}
_CREDIT_KEYWORDS = ("PAYMENT", "REFUND", "REVERSAL", "CASHBACK", "CREDIT")

_PERIOD_RE = re.compile(
    rf"(?:Statement|Billing)\s*Period\s*[:\-]?\s*(?P<start>{_ANY_DATE})\s*(?:to|-|–)\s*(?P<end>{_ANY_DATE})",
    re.IGNORECASE,
)
_SUMMARY_LABELS = {
    "purchases": r"purchases?|debits?",
    "payments_credits": r"payments?|credits?",
}


def _to_float(amount_str: str) -> float:
    return float(amount_str.replace(",", ""))


def _parse_date(text: str) -> "datetime | None":
    for shape, fmt in _DATE_SHAPES:
        if re.fullmatch(shape, text):
            try:
                # %B accepts a full month name; a 3-letter one goes through %b.
                return datetime.strptime(text, fmt if fmt != "%B %d, %Y" or len(text.split()[0]) > 3 else "%b %d, %Y")
            except ValueError:
                return None
    return None


def _classify(description: str, flag: str, plus_before_amount: bool) -> str:
    if flag.upper() in _CREDIT_FLAGS or plus_before_amount:
        return "credit"
    upper = description.upper()
    if any(re.search(rf"\b{keyword}\b", upper) for keyword in _CREDIT_KEYWORDS):
        return "credit"
    return "debit"


def _parse_line(line: str) -> "Transaction | None":
    match = _LINE_RE.match(line.strip())
    if not match:
        return None
    txn_date = _parse_date(match.group("date"))
    if txn_date is None:
        return None

    rest = match.group("rest")
    amounts = list(_AMOUNT_RE.finditer(rest))
    if not amounts:
        return None
    amount_match = amounts[-1]

    # "DESC + C 75.00": the currency marker sits between the "+" and the
    # amount, so it is trimmed before the "+" is looked for, and once more
    # after in case the order is the other way round.
    before = _CURRENCY_TAIL_RE.sub("", rest[: amount_match.start()].rstrip())
    plus_before_amount = before.endswith("+")
    if plus_before_amount:
        before = _CURRENCY_TAIL_RE.sub("", before[:-1].rstrip())
    description = _TIME_RE.sub("", before).strip()
    if not any(c.isalpha() for c in description):
        return None

    tail = rest[amount_match.end():].strip()
    flag = tail.split()[0] if tail else ""
    txn_type = _classify(description, flag, plus_before_amount)
    upper = description.upper()
    is_payment = txn_type == "credit" and "PAYMENT" in upper and "REFUND" not in upper

    return Transaction(
        date=txn_date,
        description=description,
        amount=_to_float(amount_match.group(0)),
        type=txn_type,
        reward_points=None,
        is_payment=is_payment,
    )


def _extract_period_from_text(text: str) -> "tuple[date | None, date | None]":
    match = _PERIOD_RE.search(text)
    if not match:
        return None, None
    start, end = _parse_date(match.group("start")), _parse_date(match.group("end"))
    if start is None or end is None:
        return None, None
    return start.date(), end.date()


def _extract_summary_from_text(text: str) -> dict:
    summary = {key: None for key in _SUMMARY_LABELS}
    for line in text.splitlines():
        for key, label in _SUMMARY_LABELS.items():
            if summary[key] is not None:
                continue
            match = re.search(rf"(?:{label})\b[^\d\n]*?({_AMOUNT})", line, re.IGNORECASE)
            if match:
                summary[key] = _to_float(match.group(1))
    return summary


def _all_text(pdf_path: str, password: "str | None") -> "list[str]":
    with pdfplumber.open(pdf_path, password=password) as pdf:
        return [page.extract_text() or "" for page in pdf.pages]


def parse(pdf_path: str, password: "str | None") -> ParsedStatement:
    pages = _all_text(pdf_path, password)
    transactions: "list[Transaction]" = []
    for text in pages:
        for line in text.splitlines():
            transaction = _parse_line(line)
            if transaction is not None:
                transactions.append(transaction)

    period_start, period_end = _extract_period_from_text("\n".join(pages))
    if (period_start is None or period_end is None) and transactions:
        dates = sorted(t["date"].date() for t in transactions)
        period_start, period_end = dates[0], dates[-1]

    return ParsedStatement(
        period_start=period_start, period_end=period_end, transactions=transactions
    )


def extract_summary(pdf_path: str, password: "str | None") -> dict:
    return _extract_summary_from_text("\n".join(_all_text(pdf_path, password)))
