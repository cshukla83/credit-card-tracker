from parsers.hdfc_diners import (
    _classify,
    _detect_layout_from_text,
    _extract_summary_current_layout_from_text,
    _parse_line_current_layout,
    _to_float,
)

# All merchant names, reference numbers, and amounts below are fabricated for
# testing — none of this is real transaction data.


def test_to_float_strips_commas():
    assert _to_float("1,23,456.78") == 123456.78


def test_detect_layout_current():
    assert _detect_layout_from_text("... PAYMENTS/CREDITS PURCHASES/DEBIT ...") == "current"


def test_detect_layout_legacy():
    assert _detect_layout_from_text("... Account Summary ...") == "legacy"


def test_detect_layout_unrecognized_raises():
    try:
        _detect_layout_from_text("some unrelated statement text")
    except ValueError:
        return
    raise AssertionError("expected ValueError for unrecognized layout")


def test_parse_line_plain_debit_no_points():
    line = "17/06/2026| 21:45 FAKE MERCHANT ONE BANGALORE C 216.00 l"
    txn = _parse_line_current_layout(line, credits_received_total=None)
    assert txn["type"] == "debit"
    assert txn["amount"] == 216.00
    assert txn["reward_points"] is None
    assert txn["description"] == "FAKE MERCHANT ONE BANGALORE"


def test_parse_line_debit_with_positive_points():
    line = "19/06/2026| 14:26 FAKE TRAVEL CO BANGALORE + 80 C 2,438.00 l"
    txn = _parse_line_current_layout(line, credits_received_total=None)
    assert txn["type"] == "debit"
    assert txn["reward_points"] == 80
    assert txn["amount"] == 2438.00


def test_parse_line_credit_via_bare_plus_marker():
    line = "04/07/2026| 08:15 FAKE BILLPAY GATEWAY (Ref# FAKE0000123456789) + C 19,074.00 l"
    txn = _parse_line_current_layout(line, credits_received_total=None)
    assert txn["type"] == "credit"
    assert txn["reward_points"] is None
    assert txn["amount"] == 19074.00


def test_parse_line_credit_via_negative_points_clawback():
    line = "05/02/2026| 15:07 FAKE MERCHANT TWO GURGAON - 65 + C 216.00 l"
    txn = _parse_line_current_layout(line, credits_received_total=None)
    assert txn["type"] == "credit"
    assert txn["reward_points"] == -65


def test_parse_line_credit_via_standalone_keyword():
    line = "10/06/2026| 09:00 FAKE BANK PAYMENT REF999 C 500.00 l"
    txn = _parse_line_current_layout(line, credits_received_total=None)
    assert txn["type"] == "credit"


def test_parse_line_keyword_false_positive_guard():
    # "PAYMENT" appears only inside a glued merchant/city token, not as its own
    # word -- this must NOT be classified as a credit (regression test for the
    # Session 12 fix).
    line = "10/06/2026| 09:00 FAKE SELLER PAYMENTSBANGALORE C 500.00 l"
    txn = _parse_line_current_layout(line, credits_received_total=None)
    assert txn["type"] == "debit"


def test_parse_line_amount_equality_fallback_classifies_credit():
    line = "10/06/2026| 09:00 FAKE UNLABELED CREDIT ENTRY C 1000.00 l"
    txn = _parse_line_current_layout(line, credits_received_total=1000.00)
    assert txn["type"] == "credit"


def test_parse_line_non_matching_line_returns_none():
    assert _parse_line_current_layout("Domestic Transactions", credits_received_total=None) is None


def test_classify_prioritizes_keyword_over_amount_mismatch():
    assert _classify("FAKE MERCHANT REFUND", 42.0, credits_received_total=999.0, has_credit_marker=False) == "credit"


def test_classify_defaults_to_debit():
    assert _classify("FAKE ORDINARY MERCHANT", 42.0, credits_received_total=None, has_credit_marker=False) == "debit"


def test_extract_summary_current_layout_from_text():
    text = "\n".join(
        [
            "FAKE STATEMENT HEADER",
            "PAYMENTS/CREDITS PURCHASES/DEBIT",
            "PREVIOUS STATEMENT DUES FINANCE CHARGES TOTAL AMOUNT DUE",
            "_ C1,000.00",
            "C500.00 C400.00 + C900.00 + C0.00 =",
        ]
    )
    summary = _extract_summary_current_layout_from_text(text)
    assert summary["total_amount_due"] == 1000.00
    assert summary["previous_statement_dues"] == 500.00
    assert summary["payments_credits_received"] == 400.00
    assert summary["purchases_debit"] == 900.00
    assert summary["finance_charges"] == 0.00


def test_extract_summary_current_layout_missing_fields_stay_none():
    summary = _extract_summary_current_layout_from_text("no summary information here")
    assert all(value is None for value in summary.values())
