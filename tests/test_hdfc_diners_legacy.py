from datetime import datetime

from parsers.hdfc_diners_legacy import _extract_summary_from_text, _parse_line, _to_float

# All merchant names, reference numbers, and amounts below are fabricated for
# testing — none of this is real transaction data.


def test_to_float_strips_commas():
    assert _to_float("1,23,456.78") == 123456.78


def test_parse_line_debit_no_time_no_points():
    line = "16/01/2025 FAKE GST-VPS0000000000-RATE 18.0 -29 (Ref# FAKE00000000000000) 48.87"
    txn = _parse_line(line)
    assert txn["type"] == "debit"
    assert txn["amount"] == 48.87
    assert txn["reward_points"] is None


def test_parse_line_debit_with_time_and_points():
    line = "17/01/2025 17:50:36 FAKE STORE ONE PUNE 25 811.35"
    txn = _parse_line(line)
    assert txn["type"] == "debit"
    assert txn["reward_points"] == 25
    assert txn["date"] == datetime(2025, 1, 17, 17, 50, 36)


def test_parse_line_debit_with_time_no_points():
    line = "18/01/2025 14:40:43 FAKE GROCERY APP MUMBAI 2,083.14"
    txn = _parse_line(line)
    assert txn["type"] == "debit"
    assert txn["reward_points"] is None
    assert txn["amount"] == 2083.14


def test_parse_line_credit_via_cr_suffix():
    line = "03/02/2025 05:05:15 FAKE TELE TRANSFER CREDIT (Ref# FAKE0000000000000000) 40,915.00Cr"
    txn = _parse_line(line)
    assert txn["type"] == "credit"
    assert txn["amount"] == 40915.00


def test_parse_line_rejects_numeric_only_summary_row():
    # The statement's own "Payment Due Date / Total Dues / Minimum Amount Due"
    # row is date-prefixed and number-heavy enough to otherwise match the
    # transaction regex; it must be rejected for having no letters at all.
    line = "08/03/2025 58,611.00 9,560.00"
    assert _parse_line(line) is None


def test_parse_line_non_matching_line_returns_none():
    assert _parse_line("Domestic Transactions") is None


def test_extract_summary_from_text():
    text = "\n".join(
        [
            "FAKE STATEMENT HEADER",
            "Account Summary",
            "Opening Payment/ Purchase/ Finance",
            "Total Dues",
            "Balance Credits Debits Charges",
            "40,914.90 40,915.00 58,611.21 0.00 58,611.00",
        ]
    )
    summary = _extract_summary_from_text(text)
    assert summary["previous_statement_dues"] == 40914.90
    assert summary["payments_credits_received"] == 40915.00
    assert summary["purchases_debit"] == 58611.21
    assert summary["finance_charges"] == 0.00
    assert summary["total_amount_due"] == 58611.00


def test_extract_summary_ignores_five_number_lines_before_header():
    # A same-shaped 5-number line appearing before "Account Summary" (e.g. a
    # GST summary row elsewhere on the page) must not be mistaken for the
    # real summary line.
    text = "\n".join(
        [
            "48.87 0.00 0.00 0.00 48.87",
            "Account Summary",
            "40,914.90 40,915.00 58,611.21 0.00 58,611.00",
        ]
    )
    summary = _extract_summary_from_text(text)
    assert summary["previous_statement_dues"] == 40914.90


def test_extract_summary_missing_header_stays_none():
    summary = _extract_summary_from_text("no summary information here")
    assert all(value is None for value in summary.values())
