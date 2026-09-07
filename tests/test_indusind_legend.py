from datetime import date

import pytest

from parsers.indusind.indusind_legend import (
    _classify,
    _extract_period_from_text,
    _extract_summary_from_text,
    _parse_line,
    _to_float,
)

# All merchant names, cardholder names, card numbers and amounts below are
# fabricated for testing -- none of this is real transaction data.


def test_to_float_strips_commas():
    assert _to_float("1,08,109.51") == 108109.51


def test_parse_line_plain_debit():
    txn = _parse_line("16/12/2025 FAKE MERCHANT ONE BENGALURU IN 17 1,700.12 DR")
    assert txn["type"] == "debit"
    assert txn["amount"] == 1700.12
    assert txn["reward_points"] == 17
    assert txn["description"] == "FAKE MERCHANT ONE BENGALURU IN"


def test_parse_line_credit():
    txn = _parse_line("02/01/2026 FAKE BILLPAY GATEWAY 0 18,938.00 CR")
    assert txn["type"] == "credit"
    assert txn["amount"] == 18938.00
    assert txn["reward_points"] == 0


def test_parse_line_credit_with_negative_points_clawback():
    txn = _parse_line("27/12/2025 FAKE PAYMENT PROCESSOR IN -17 871.06 CR")
    assert txn["type"] == "credit"
    assert txn["reward_points"] == -17
    assert txn["amount"] == 871.06


def test_parse_line_date_parsed_as_day_first():
    # DD/MM/YYYY -- 06/07 must read as 6 July, not 7 June.
    txn = _parse_line("06/07/2026 FAKE MERCHANT TWO 5 100.00 DR")
    assert txn["date"].date() == date(2026, 7, 6)


def test_parse_line_with_merchant_category_on_same_line():
    txn = _parse_line("16/12/2025 FAKE MERCHANT THREE BENGALURU IN GROCERY & 10 986.00 DR")
    assert txn["amount"] == 986.00
    assert txn["reward_points"] == 10


# --- Sidebar-bleed cases -------------------------------------------------
# The page-1 summary box is a right-hand sidebar that text extraction merges
# onto the end of whichever transaction row shares its vertical position. These
# are the rows that a end-anchored regex would drop, or a greedy one would
# misread.


def test_parse_line_tolerates_trailing_sidebar_label():
    txn = _parse_line("16/12/2025 FAKE MERCHANT FOUR IN GROCERY & 10 986.00 DR Total Outstanding")
    assert txn["amount"] == 986.00
    assert txn["type"] == "debit"


def test_parse_line_trailing_sidebar_amount_does_not_win():
    # The line ends with a SECOND amount/marker pair belonging to the sidebar.
    # The transaction's own amount is the leftmost one and must be the one kept.
    txn = _parse_line("16/12/2025 FAKE MERCHANT FIVE IN GROCERY & 6 618.00 DR 5,302.11 DR")
    assert txn["amount"] == 618.00
    assert txn["amount"] != 5302.11
    assert txn["reward_points"] == 6


def test_parse_line_tolerates_trailing_sidebar_parenthetical():
    txn = _parse_line("17/01/2026 FAKE MERCHANT SIX IN GROCERY & 4 218.00 DR (includingLoans)")
    assert txn["amount"] == 218.00


# --- Marker classification ------------------------------------------------


@pytest.mark.parametrize("marker,expected", [("DR", "debit"), ("CR", "credit")])
def test_classify_known_markers(marker, expected):
    assert _classify(marker) == expected


@pytest.mark.parametrize("marker", ["XX", "DRR", "CD", "TR"])
def test_classify_unknown_marker_raises(marker):
    with pytest.raises(ValueError):
        _classify(marker)


def test_parse_line_unknown_marker_raises_not_silently_dropped():
    # Regression guard on a specific design choice: the line regex captures the
    # marker loosely and validates it in _classify(), so an unfamiliar marker
    # raises. A strict (DR|CR) alternation would instead fail to match and drop
    # the row silently -- the failure this test exists to prevent.
    with pytest.raises(ValueError):
        _parse_line("16/12/2025 FAKE MERCHANT SEVEN IN 5 100.00 XX")


@pytest.mark.parametrize("marker,expected", [("DR", "debit"), ("CR", "credit")])
def test_parse_line_marker_drives_type(marker, expected):
    txn = _parse_line(f"16/12/2025 FAKE MERCHANT EIGHT IN 5 500.00 {marker}")
    assert txn["type"] == expected


# --- Interleaved non-transaction rows -------------------------------------


def test_parse_line_payment_section_header_returns_none():
    assert (
        _parse_line("Payment Details for MR FAKE NAME (Credit Card No. 4147XXXXXXXX0000)") is None
    )


def test_parse_line_purchases_section_header_returns_none():
    assert (
        _parse_line(
            "Purchases & Cash Transactions for MR FAKE NAME (Credit Card No. 4147XXXXXXXX0000)"
        )
        is None
    )


def test_parse_line_subtotal_returns_none():
    assert _parse_line("Total 62 6,173.12") is None
    assert _parse_line("Total -17 19,809.06") is None


def test_parse_line_wrapped_category_continuation_returns_none():
    # The tail of a merchant category that wrapped off the dated line.
    assert _parse_line("SUPERMARKET") is None


def test_parse_line_non_transaction_returns_none():
    assert _parse_line("INDUSIND BANK LEGEND CREDIT CARD STATEMENT") is None
    assert _parse_line("Date TransactionDetails MerchantCategory Amount(in )") is None


def test_parse_line_bare_sidebar_date_returns_none():
    # The payment-due-date sidebar value is a bare date, sometimes with an
    # amount after it -- neither is a transaction.
    assert _parse_line("04/02/2026") is None
    assert _parse_line("04/02/2026 107.00") is None


# --- Billing period --------------------------------------------------------


def test_extract_period():
    start, end = _extract_period_from_text("Points 16/12/2025 To 15/01/2026")
    assert start == date(2025, 12, 16)
    assert end == date(2026, 1, 15)


def test_extract_period_spanning_year_boundary():
    start, end = _extract_period_from_text("16/12/2025 To 15/01/2026")
    assert start <= end


def test_extract_period_absent_returns_none():
    assert _extract_period_from_text("no period anywhere here") == (None, None)


# --- Summary box -----------------------------------------------------------

_SUMMARY_TEXT = """INDUSIND BANK LEGEND CREDIT CARD STATEMENT
Previous Balance
11,111.11 DR
Purchases & Other Charges
2,222.22
Cash Advance
0.00
Payment & Other Credits
Credit Credit Limit Available Credit Limit Cash Limit Available Cash Limit 3,333.33
Summary
6,00,000.00 5,94,697.89 1,20,000.00 1,20,000.00
Minimum Amount Due
444.44
"""


def test_extract_summary_reads_each_label():
    summary = _extract_summary_from_text(_SUMMARY_TEXT)
    assert summary["previous_balance"] == 11111.11
    assert summary["purchases_charges"] == 2222.22
    assert summary["cash_advance"] == 0.00
    assert summary["minimum_amount_due"] == 444.44


def test_extract_summary_takes_last_amount_when_sidebar_line_has_merged_text():
    # "Payment & Other Credits" has its value merged onto the end of an
    # unrelated credit-limit header row; the value is the LAST amount there.
    summary = _extract_summary_from_text(_SUMMARY_TEXT)
    assert summary["payments_credits"] == 3333.33


def test_extract_summary_renamed_label_yields_none_not_wrong_value():
    scrambled = _SUMMARY_TEXT.replace("Purchases & Other Charges", "Purchases And Charges")
    summary = _extract_summary_from_text(scrambled)
    assert summary["purchases_charges"] is None
    # The other fields must be unaffected -- a rename breaks one field, not the
    # whole box.
    assert summary["previous_balance"] == 11111.11


def test_extract_summary_prose_paragraph_does_not_hijack_minimum_amount_due():
    # "Minimum Amount Due" also opens a prose paragraph on the real page 1. The
    # label match is end-anchored so the paragraph cannot win.
    with_prose = _SUMMARY_TEXT.replace(
        "Minimum Amount Due\n444.44",
        "Minimum Amount Due (MAD) calculation on your card has been revised 9,999.99 DR\n"
        "some following prose line\n"
        "Minimum Amount Due\n444.44",
    )
    summary = _extract_summary_from_text(with_prose)
    assert summary["minimum_amount_due"] == 444.44


def test_extract_summary_absent_block_yields_all_none():
    summary = _extract_summary_from_text("nothing resembling a summary box here")
    assert all(value is None for value in summary.values())
