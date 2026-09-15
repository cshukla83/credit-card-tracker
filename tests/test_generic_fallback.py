from datetime import date, datetime

import pytest

from parsers.generic_fallback import (
    _extract_period_from_text,
    _extract_summary_from_text,
    _parse_line,
    parse,
)

# Session 99: the bank-agnostic best-attempt parser. Every merchant, amount
# and date here is fabricated.


# --- _parse_line: one shape per known bank layout, none named ----------------


def test_line_slash_date_currency_marker_and_trailing_token():
    # "DD/MM/YYYY| HH:MM DESC C 1,234.00 l" shape
    txn = _parse_line("17/06/2026| 21:45 FAKE MERCHANT C 216.00 l")
    assert txn["date"] == datetime(2026, 6, 17)
    assert txn["description"] == "FAKE MERCHANT"
    assert txn["amount"] == 216.00
    assert txn["type"] == "debit"
    assert txn["reward_points"] is None
    assert txn["is_payment"] is False


def test_line_plus_before_amount_is_credit():
    txn = _parse_line("15/01/2026| 12:00 SOME REVERSAL + C 75.00 l")
    assert txn["type"] == "credit"
    assert txn["description"] == "SOME REVERSAL"


def test_line_two_digit_year_and_flag():
    # "DD Mon YY DESC 3,865.00 D" shape; C flag means credit
    debit = _parse_line("18 Feb 26 FAKE MERCHANT ONE IN 3,865.00 D")
    credit = _parse_line("07 Mar 26 SOME STORE 1,08,110.00 C")
    assert debit["date"] == datetime(2026, 2, 18)
    assert debit["amount"] == 3865.00
    assert debit["type"] == "debit"
    assert credit["amount"] == 108110.00
    assert credit["type"] == "credit"


def test_line_trailing_cr_flag_and_last_amount_wins():
    # "DD/MM/YYYY serial DESC points intl_amount amount CR" shape: the last
    # amount is the one; earlier numbers stay in the description.
    txn = _parse_line("01/04/2026 123 FAKE INTL SHOP 45 12.50 1,050.00 CR")
    assert txn["amount"] == 1050.00
    assert txn["type"] == "credit"
    assert "FAKE INTL SHOP" in txn["description"]


def test_line_keyword_credit_and_payment_flag():
    txn = _parse_line("02-02-2026 PAYMENT RECEIVED THANK YOU 500.00")
    assert txn["type"] == "credit"
    assert txn["is_payment"] is True
    refund = _parse_line("02-02-2026 REFUND PAYMENT ADJUSTMENT 20.00")
    assert refund["type"] == "credit"
    assert refund["is_payment"] is False


def test_line_keyword_is_whole_word():
    # "PAYMENTS" glued into a merchant name is not a credit keyword.
    assert _parse_line("03/03/2026 FAKE SELLER PAYMENTSCITY 99.00")["type"] == "debit"


@pytest.mark.parametrize(
    "line",
    [
        "Total amount due 1,234.00",  # no date
        "05/01/2026 1234 5678 90.00",  # no letters in the description
        "05/01/2026 FAKE MERCHANT",  # no amount
        "05 Jan FAKE MERCHANT 10.00",  # no year
        "some text 05/01/2026 FAKE MERCHANT 10.00",  # date not at line start
    ],
)
def test_line_rejects_non_transactions(line):
    assert _parse_line(line) is None


# --- period and summary -----------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Billing Period 17 Jun, 2026 - 16 Jul, 2026",
        "Statement Period: 17 Jun 26 to 16 Jul 26",
        "statement period 17/06/2026 To 16/07/2026",
    ],
)
def test_period_shapes(text):
    assert _extract_period_from_text(text) == (date(2026, 6, 17), date(2026, 7, 16))


def test_period_missing():
    assert _extract_period_from_text("no period here") == (None, None)


def test_summary_labels_with_amount_on_same_line():
    text = "Purchases & Other Charges 1,500.00\nPayment & Other Credits 200.00\n"
    assert _extract_summary_from_text(text) == {"purchases": 1500.0, "payments_credits": 200.0}


def test_summary_labels_without_figures_are_none():
    text = "PAYMENTS/CREDITS PURCHASES/DEBITS\nC 0.00 C 75.00 C 150.00 C 0.00 =\n"
    assert _extract_summary_from_text(text) == {"purchases": None, "payments_credits": None}


# --- parse(): whole synthetic statements ------------------------------------


def test_parse_unknown_layout_end_to_end(make_pdf, tmp_path):
    path = tmp_path / "s.pdf"
    path.write_bytes(
        make_pdf(
            [
                "FAKE BANK Platinum statement",
                "Statement Period: 01/01/2026 to 31/01/2026",
                "Purchases 150.00",
                "Payments 75.00",
                "05/01/2026 FAKE SHOP ONE 100.00",
                "10/01/2026 FAKE SHOP TWO 50.00",
                "15/01/2026 PAYMENT RECEIVED 75.00 CR",
                "Total amount due 75.00",
            ]
        )
    )
    parsed = parse(str(path), None)
    assert parsed["period_start"] == date(2026, 1, 1)
    assert parsed["period_end"] == date(2026, 1, 31)
    assert [(t["type"], t["amount"]) for t in parsed["transactions"]] == [
        ("debit", 100.0),
        ("debit", 50.0),
        ("credit", 75.0),
    ]


def test_parse_period_falls_back_to_transaction_dates(make_pdf, tmp_path):
    path = tmp_path / "s.pdf"
    path.write_bytes(make_pdf(["10/01/2026 FAKE SHOP 10.00", "03/01/2026 FAKE SHOP 20.00"]))
    parsed = parse(str(path), None)
    assert (parsed["period_start"], parsed["period_end"]) == (date(2026, 1, 3), date(2026, 1, 10))


def test_parse_nothing_transaction_like(make_pdf, tmp_path):
    path = tmp_path / "s.pdf"
    path.write_bytes(make_pdf(["Just a letter", "with no rows at all"]))
    parsed = parse(str(path), None)
    assert parsed["transactions"] == []
    assert parsed["period_start"] is None


# --- real samples, treated as unrecognised (skip without local PDFs) --------
# The fallback must produce something reconciliation-checkable from a real
# statement: rows found, a period, both sums computed. Whether it *matches*
# is not asserted -- that is what the gate is for. Counts only.

import os
from pathlib import Path

from parsers.reconcile import reconcile
from parsers.registry import BANKS
from tests.test_upload_detect import _REAL_CASES


@pytest.mark.parametrize("bank, pdf_path", _REAL_CASES)
def test_real_statement_as_unrecognised_is_checkable(bank, pdf_path):
    password = os.environ.get(BANKS[bank].password_env_key)
    if not password:
        pytest.skip(f"{BANKS[bank].password_env_key} not set in .env")
    if not Path(pdf_path).exists():
        pytest.skip(f"{pdf_path} not present locally")

    parsed = parse(pdf_path, password)
    assert len(parsed["transactions"]) > 0
    assert parsed["period_start"] is not None and parsed["period_end"] is not None
    assert parsed["period_start"] <= parsed["period_end"]
    assert all(t["type"] in ("debit", "credit") for t in parsed["transactions"])
    result = reconcile(parsed["transactions"], None, None)
    assert result["status"] == "unverified"  # no expected figures given (Session 114)
    assert result["debit"]["parsed"] > 0
