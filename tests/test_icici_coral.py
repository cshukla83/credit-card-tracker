from parsers.icici_coral import (
    _classify,
    _extract_period_from_text,
    _extract_summary_from_text,
    _parse_line,
    _to_float,
)

# All merchant names, reference numbers, and amounts below are fabricated for
# testing -- none of this is real transaction data.


def test_to_float_strips_commas():
    assert _to_float("1,23,456.78") == 123456.78


def test_classify_credit():
    assert _classify(has_credit_marker=True) == "credit"


def test_classify_debit():
    assert _classify(has_credit_marker=False) == "debit"


def test_parse_line_plain_debit_zero_points():
    line = "17/03/2026 13067759173 FAKE PETROLEUM BANGALORE IN 0 1,199.51"
    txn = _parse_line(line)
    assert txn["type"] == "debit"
    assert txn["amount"] == 1199.51
    assert txn["reward_points"] == 0
    assert txn["description"] == "FAKE PETROLEUM BANGALORE IN"


def test_parse_line_debit_with_positive_points():
    line = "17/03/2026 13068001383 FAKE TECHNOLOGIES GURGAON IN 46 2,349.00"
    txn = _parse_line(line)
    assert txn["type"] == "debit"
    assert txn["reward_points"] == 46
    assert txn["amount"] == 2349.00


def test_parse_line_credit_via_cr_suffix():
    line = "01/04/2026 13150014837 FAKE BBPS PAYMENT RECEIVED 0 2,860.00 CR"
    txn = _parse_line(line)
    assert txn["type"] == "credit"
    assert txn["reward_points"] == 0
    assert txn["amount"] == 2860.00
    assert txn["description"] == "FAKE BBPS PAYMENT RECEIVED"


def test_parse_line_credit_with_negative_points_clawback():
    line = "13/04/2026 13228121114 FAKE RAILWAYS NEW DELHI IN -3 175.00 CR"
    txn = _parse_line(line)
    assert txn["type"] == "credit"
    assert txn["reward_points"] == -3
    assert txn["amount"] == 175.00


def test_parse_line_negative_points_without_credit_marker():
    # No real sample showed negative points on a plain debit row, but the
    # sign should be parsed independently of the credit marker -- regex
    # robustness check, not a documented real-world case.
    line = "05/04/2026 13181219584 FAKE RETAIL CONCEPT BANGALORE IN -2 217.38"
    txn = _parse_line(line)
    assert txn["type"] == "debit"
    assert txn["reward_points"] == -2


def test_parse_line_with_international_amount_uses_final_amount():
    # Fabricated: an international-amount field between reward points and the
    # final (INR) amount. The sample statement never exercised this column,
    # so this is a defensive/structural test, not a reproduction of real data.
    line = "10/04/2026 13209680930 FAKE AIRLINE MUMBAI IN 32 19.50 1,600.00"
    txn = _parse_line(line)
    assert txn["amount"] == 1600.00
    assert txn["reward_points"] == 32
    assert txn["type"] == "debit"


def test_parse_line_with_leading_category_breakdown_noise():
    # Regression case for Session 27's finding: the pie-chart category legend
    # (e.g. "7% 31%") sometimes lands on the same raw-text line as a real
    # transaction, ahead of the date. The noise prefix must be ignored, not
    # cause the line to fail to parse or corrupt the description.
    line = "7% 31% 17/03/2026 13067759173 FAKE PETROLEUM BANGALORE IN 0 1,199.51"
    txn = _parse_line(line)
    assert txn is not None
    assert txn["amount"] == 1199.51
    assert txn["description"] == "FAKE PETROLEUM BANGALORE IN"


def test_parse_line_category_only_line_returns_none():
    assert _parse_line("Travel-16% Apparel/Grocery-46%") is None


def test_parse_line_header_returns_none():
    line = "Date SerNo. Transaction Details Reward Points Intl.# amount Amount (in`)"
    assert _parse_line(line) is None


def test_parse_line_masked_card_number_returns_none():
    assert _parse_line("4375XXXXXXXX4008") is None


def test_extract_period_from_text():
    text = "Statement period : March 17, 2026 to April 16, 2026"
    period_start, period_end = _extract_period_from_text(text)
    assert period_start.isoformat() == "2026-03-17"
    assert period_end.isoformat() == "2026-04-16"


def test_extract_period_from_text_missing_returns_none_none():
    period_start, period_end = _extract_period_from_text("no period information here")
    assert period_start is None
    assert period_end is None


def test_extract_summary_from_text():
    text = "\n".join(
        [
            "STATEMENT SUMMARY",
            "Total Amount due",
            "`5,000.00 = + + -",
            "Minimum Amount due CREDIT SUMMARY",
            "`250.00",
            "Previous Balance Purchases / Charges Cash Advances Payments / Credits",
            "`1,000.00 `4,500.00 `0.00 `500.00",
        ]
    )
    summary = _extract_summary_from_text(text)
    assert summary["total_amount_due"] == 5000.00
    assert summary["minimum_amount_due"] == 250.00
    assert summary["previous_balance"] == 1000.00
    assert summary["purchases_charges"] == 4500.00
    assert summary["cash_advances"] == 0.00
    assert summary["payments_credits"] == 500.00


def test_extract_summary_from_text_missing_fields_stay_none():
    summary = _extract_summary_from_text("no summary information here")
    assert all(value is None for value in summary.values())
