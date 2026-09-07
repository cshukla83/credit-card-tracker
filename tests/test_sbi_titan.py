from datetime import date

import pytest

from parsers.sbi.sbi_titan import (
    _classify,
    _extract_period_from_text,
    _extract_summary_from_text,
    _parse_line,
    _to_float,
)

# All merchant names, cardholder names, reference numbers and amounts below are
# fabricated for testing -- none of this is real transaction data.


def test_to_float_strips_commas():
    # SBI prints amounts in the Indian grouping style (lakh/crore separators).
    assert _to_float("1,08,109.51") == 108109.51


def test_parse_line_plain_debit():
    txn = _parse_line("18 Feb 26 FAKE MERCHANT ONE IN 3,865.00 D")
    assert txn["type"] == "debit"
    assert txn["amount"] == 3865.00
    assert txn["description"] == "FAKE MERCHANT ONE IN"
    assert txn["reward_points"] is None


def test_parse_line_credit():
    txn = _parse_line("07 Mar 26 PAYMENT RECEIVED 000FAKE0000000000 1,08,110.00 C")
    assert txn["type"] == "credit"
    assert txn["amount"] == 108110.00
    assert txn["description"] == "PAYMENT RECEIVED 000FAKE0000000000"


def test_parse_line_description_containing_digits_and_dashes():
    # UPI descriptions run words, digits and dashes together; the amount must
    # still be split off correctly rather than being absorbed into the text.
    txn = _parse_line("15 Mar 26 UPI-FAKE STORE 24X7 202.36 D")
    assert txn["description"] == "UPI-FAKE STORE 24X7"
    assert txn["amount"] == 202.36


def test_parse_line_two_digit_year_becomes_full_date():
    txn = _parse_line("26 Dec 25 FAKE MERCHANT TWO 22.00 D")
    assert txn["date"].date() == date(2025, 12, 26)


def test_parse_line_reward_points_always_none():
    # SBI reports points only in aggregate, never per transaction.
    txn = _parse_line("20 Mar 26 FAKE MERCHANT THREE 360.00 D")
    assert txn["reward_points"] is None


@pytest.mark.parametrize(
    "flag,expected",
    [
        ("C", "credit"),
        ("T", "credit"),
        ("D", "debit"),
        ("EN", "debit"),
        ("FP", "debit"),
        ("EMD", "debit"),
        ("BT", "debit"),
        ("M", "debit"),
    ],
)
def test_classify_known_flags(flag, expected):
    assert _classify(flag) == expected


@pytest.mark.parametrize("flag", ["X", "TAD", "ZZ"])
def test_classify_unknown_flag_raises(flag):
    # Must raise rather than silently defaulting to debit -- a wrong-sided
    # transaction breaks reconciliation without any visible error.
    with pytest.raises(ValueError):
        _classify(flag)


def test_parse_line_unknown_flag_raises():
    with pytest.raises(ValueError):
        _parse_line("18 Feb 26 FAKE MERCHANT FOUR 100.00 X")


@pytest.mark.parametrize(
    "flag,expected",
    [("C", "credit"), ("T", "credit"), ("D", "debit"), ("EN", "debit"), ("BT", "debit")],
)
def test_parse_line_flag_drives_type(flag, expected):
    txn = _parse_line(f"18 Feb 26 FAKE MERCHANT FIVE 500.00 {flag}")
    assert txn["type"] == expected


def test_parse_line_cardholder_header_returns_none():
    assert _parse_line("TRANSACTIONS FOR FAKE CARDHOLDER NAME") is None


def test_parse_line_non_transaction_returns_none():
    assert _parse_line("REWARD SUMMARY") is None
    assert _parse_line("Date Transaction Details Amount ( ` )") is None


def test_extract_period():
    text = "Date Transaction Details Amount ( ` )\nfor Statement Period: 17 Feb 26 to 16 Mar 26\n"
    start, end = _extract_period_from_text(text)
    assert start == date(2026, 2, 17)
    assert end == date(2026, 3, 16)


def test_extract_period_spanning_year_boundary():
    text = "for Statement Period: 26 Dec 25 to 16 Jan 26"
    start, end = _extract_period_from_text(text)
    assert start == date(2025, 12, 26)
    assert end == date(2026, 1, 16)
    assert start <= end


def test_extract_period_absent_returns_none():
    assert _extract_period_from_text("no period anywhere here") == (None, None)


_SUMMARY_TEXT = """ACCOUNT SUMMARY
Additions
Payments,
Previous Balance Reversals & other Purchases & Other Fee, Taxes & Total Outstanding
( ` ) Credits ( ` ) Debits ( ` ) Interest Charges( ` ) ( ` )
1,11,111.11 2,22,222.22 33,333.33 44.44 55,555.55
TITAN BENEFITS SUMMARY
"""


def test_extract_summary_maps_each_value_to_its_label():
    summary = _extract_summary_from_text(_SUMMARY_TEXT)
    assert summary["previous_balance"] == 111111.11
    assert summary["payments_credits"] == 222222.22
    assert summary["purchases_debits"] == 33333.33
    assert summary["fees_taxes_interest"] == 44.44
    assert summary["total_outstanding"] == 55555.55


def test_extract_summary_unrecognized_layout_yields_no_values():
    # A reordered or renamed label row must fail to match outright rather than
    # mapping the value row onto the wrong labels.
    scrambled = _SUMMARY_TEXT.replace("Previous Balance", "Opening Balance")
    summary = _extract_summary_from_text(scrambled)
    assert all(value is None for value in summary.values())
