from __future__ import annotations

import re
from datetime import date, datetime

import pdfplumber

from parsers.base import ParsedStatement, Transaction, is_payment_credit

# Lead tokens of an SBI Titan credit line that is a payment to the card
# (Session 61): a fixed "payment received" phrase followed by a reference.
# Refund and waiver credits carry merchant / fee text instead.
_PAYMENT_PREFIXES = ("PAYMENT RECEIVED",)

# Matches one transaction line as it comes out of pdfplumber's extract_text(),
# e.g. "18 Feb 26 SOME MERCHANT IN 3,865.00 D" or, on a credit row,
# "07 Mar 26 PAYMENT RECEIVED 000DP01606617 1,08,110.00 C".
#
# Anchored at both ends (match() + "$") rather than searched: unlike the ICICI
# layout there's no chart legend bleeding into transaction rows here, so a
# strict anchor is safe and keeps prose lines elsewhere in the statement from
# being mistaken for transactions.
#
# Deliberately NOT built on extract_table(): pdfplumber returns this table as a
# single row whose three cells are newline-joined blobs of 22+ dates, 23+
# description lines and 22+ amounts. The description column has one MORE entry
# than the other two (the "TRANSACTIONS FOR <NAME>" header lines live in it),
# so zipping the columns back together silently misaligns every row after the
# first cardholder header. Session 31 flagged this; extract_text() plus a
# date-anchored regex sidesteps it entirely.
#
# There is no reward-points column: SBI reports points only in the aggregate
# REWARD SUMMARY / SAVINGS AND BENEFITS blocks, never per transaction.
_TXN_LINE_RE = re.compile(
    r"^(?P<date>\d{2} [A-Za-z]{3} \d{2})\s+"
    r"(?P<desc>.*?)\s+"
    r"(?P<amount>[\d,]+\.\d{2})\s+"
    r"(?P<flag>[A-Z]{1,3})$"
)

# The transaction table's column header carries the billing period, e.g.
# "for Statement Period: 17 Feb 26 to 16 Mar 26".
#
# NOTE: both sides use the SAME two-digit-year "DD Mon YY" form as the
# transaction lines -- verified against all four sample statements. (An earlier
# assumption that headers used a four-digit year did not survive contact with
# the real text.) The header repeats on page 2 when transactions spill over, so
# the first match found while scanning pages in order is used.
_PERIOD_RE = re.compile(
    r"Statement Period:\s*(?P<start>\d{2} [A-Za-z]{3} \d{2})\s+to\s+"
    r"(?P<end>\d{2} [A-Za-z]{3} \d{2})"
)

# Cardholder section headers inside the transaction table, e.g.
# "TRANSACTIONS FOR JANE DOE". They partition the rows below them by
# cardholder (primary vs. add-on card).
#
# TODO: cardholder attribution is dropped. Transaction has no field for it and
# storage/ has no column, so which cardholder made a spend is lost on import.
# Worth adding when per-cardholder breakdowns are wanted -- the information IS
# recoverable from the text, it's just discarded here.
_CARDHOLDER_HEADER_RE = re.compile(r"^TRANSACTIONS FOR\b")

# Flag characters trailing each amount. The statement prints its own legend:
#   "C=Credit ; D=Debit; EN=Encash; FP=Flexipay; EMD=Easy Money Draft;
#    BT=Balance Transfer; M=Monthly Installments; TAD=Total Amount Due;
#    T=Temporary Credit."
#
# Only C and D actually occur across the four sample statements; the rest are
# mapped from the legend's own wording so an unusual statement parses rather
# than blowing up. TAD is intentionally absent -- it labels a summary figure,
# not a transaction, so a row flagged TAD means the regex matched something it
# shouldn't have and should surface as an error.
#
# Money coming back to the cardholder is a credit; anything that increases what
# is owed (including drawdown products like Encash and Flexipay) is a debit.
_FLAG_TO_TYPE = {
    "C": "credit",
    "T": "credit",  # temporary credit pending dispute resolution
    "D": "debit",
    "EN": "debit",  # Encash
    "FP": "debit",  # Flexipay
    "EMD": "debit",  # Easy Money Draft
    "BT": "debit",  # Balance Transfer
    "M": "debit",  # Monthly Installments
}

# The page-1 ACCOUNT SUMMARY block. In extract_text() output the five labels
# wrap across two lines and the five values land together on a third:
#
#   ACCOUNT SUMMARY
#   Additions
#   Payments,
#   Previous Balance Reversals & other Purchases & Other Fee, Taxes & Total Outstanding
#   ( ` ) Credits ( ` ) Debits ( ` ) Interest Charges( ` ) ( ` )
#   1,08,109.51 1,11,218.00 41,362.11 0.00 38,254.00
#
# The labels are therefore not positionally adjacent to their values in the
# text, so each value can't be matched to a neighbouring label directly. What
# this regex does instead is require the label fragments to appear in a known
# ORDER before consuming the value row -- so the value-to-label mapping is
# validated by the layout rather than assumed from position alone, and a
# statement whose columns were reordered or renamed fails to match (summary
# comes back empty) instead of silently mapping values to the wrong labels.
# The backtick is a font-encoding artifact standing in for the rupee symbol.
_ACCOUNT_SUMMARY_RE = re.compile(
    r"ACCOUNT SUMMARY\s*\n"
    r"[^\n]*\n"  # "Additions"
    r"[^\n]*\n"  # "Payments,"
    r"\s*Previous Balance\s+Reversals & other\s+Purchases & Other\s+"
    r"Fee, Taxes &\s+Total Outstanding\s*\n"
    r"[^\n]*Credits[^\n]*Debits[^\n]*Interest Charges[^\n]*\n"
    r"\s*`?(?P<previous_balance>[\d,]+\.\d{2})\s+"
    r"`?(?P<payments_credits>[\d,]+\.\d{2})\s+"
    r"`?(?P<purchases_debits>[\d,]+\.\d{2})\s+"
    r"`?(?P<fees_taxes_interest>[\d,]+\.\d{2})\s+"
    r"`?(?P<total_outstanding>[\d,]+\.\d{2})"
)


def _to_float(amount_str: str) -> float:
    return float(amount_str.replace(",", ""))


def _classify(flag: str) -> str:
    """Map a trailing flag character to "debit" or "credit".

    Raises ValueError on an unrecognized flag rather than defaulting to debit:
    a silent default here would land a credit on the wrong side of the ledger
    and quietly break reconciliation, which is exactly the class of bug that is
    hardest to notice after import.
    """
    try:
        return _FLAG_TO_TYPE[flag]
    except KeyError:
        raise ValueError(
            f"unknown SBI transaction flag {flag!r} "
            f"(known flags: {', '.join(sorted(_FLAG_TO_TYPE))})"
        ) from None


def _parse_line(line: str) -> "Transaction | None":
    """Parse one text line into a Transaction, or None if it isn't one.

    Returns None for cardholder section headers ("TRANSACTIONS FOR <NAME>").
    Those sit inside the transaction table but carry no date, so the
    date-anchored regex would reject them anyway -- they're checked for
    explicitly first so the skip is intentional and testable rather than
    incidental.
    """
    stripped = line.strip()

    if _CARDHOLDER_HEADER_RE.match(stripped):
        return None

    match = _TXN_LINE_RE.match(stripped)
    if not match:
        return None

    # Two-digit year: "17 Feb 26" -> 2026-02-17. %y maps 00-68 to 2000-2068,
    # which comfortably covers any statement this tracker will see.
    txn_date = datetime.strptime(match.group("date"), "%d %b %y")
    description = match.group("desc").strip()
    txn_type = _classify(match.group("flag"))

    return Transaction(
        date=txn_date,
        description=description,
        amount=_to_float(match.group("amount")),
        type=txn_type,
        is_payment=is_payment_credit(txn_type, description, _PAYMENT_PREFIXES),
        # Always None: SBI reports reward points only in aggregate (the REWARD
        # SUMMARY and SAVINGS AND BENEFITS blocks), never per transaction, so
        # there is nothing per-row to record.
        reward_points=None,
    )


def _extract_period_from_text(text: str) -> "tuple[date | None, date | None]":
    match = _PERIOD_RE.search(text)
    if not match:
        return None, None
    period_start = datetime.strptime(match.group("start"), "%d %b %y").date()
    period_end = datetime.strptime(match.group("end"), "%d %b %y").date()
    return period_start, period_end


def _extract_summary_from_text(text: str) -> dict:
    summary = {
        "previous_balance": None,
        "payments_credits": None,
        "purchases_debits": None,
        "fees_taxes_interest": None,
        "total_outstanding": None,
    }

    match = _ACCOUNT_SUMMARY_RE.search(text)
    if match:
        for key in summary:
            summary[key] = _to_float(match.group(key))

    return summary


def _parse_transactions(pdf_path: str, password: str) -> "list[Transaction]":
    """Collect transactions from EVERY page, not just page 1.

    Session 31 found that two of the four SBI samples continue the transaction
    table onto page 2 (the "Statement Period" column header repeats there).
    Later pages are boilerplate -- schedule of charges, terms -- and contain no
    date-anchored, flag-terminated lines, so scanning them costs nothing and
    yields no false positives.

    NOTE on grey-highlighted rows: the statement's own footnote says
    "Transactions highlighted in grey color, if any, do not form part of
    Purchases & Other Debits; #Transactions fully/partially converted to
    Flexipay/Encash/Merchant EMI." Those rows are distinguished *visually* in
    the PDF -- extract_text() returns them identically to any other row, with
    no grey marker and (in these four samples) no "#" either. There is
    therefore nothing in the text to exclude them by, and none of the four
    samples appears to contain any. If a future statement fails to reconcile,
    THIS is the first thing to investigate: a grey row would be counted as a
    normal debit here and inflate the debit total. Detecting it would mean
    dropping to pdfplumber's rect/char objects to read fill colour, rather than
    extract_text().
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

    # The period header lives on page 1, but scan pages in order and take the
    # first match so a layout that pushes the table onto a later page still
    # finds it.
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
