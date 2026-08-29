import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

import parsers.icici as icici_dispatch
from parsers.icici_coral import extract_summary

# These tests run the parser against the real sample statement PDFs in
# data/statements/ (git-ignored, not part of the repo) using the real password
# from .env (also git-ignored). They skip automatically if either isn't present
# locally, so the suite still passes for anyone who clones the repo without
# them. Only reconciliation results and counts are asserted on -- never real
# amounts, dates, or merchant descriptions.
#
# parse() goes through the parsers.icici dispatch layer (card_type="Coral") so
# the dispatch path itself is exercised, not just the Coral implementation
# directly. extract_summary() is Coral-specific reconciliation tooling, not part
# of the dispatch interface, so it's imported straight from parsers.icici_coral.
#
# Unlike the HDFC suite there is no layout-detection test here: ICICI Coral has
# a single known statement layout, so parsers/icici_coral.py has no
# _detect_layout() counterpart to assert on. A period-sanity check stands in.

load_dotenv()

PASSWORD = os.environ.get("ICICI_SAMPLE_PASSWORD")

SAMPLES = [
    "data/statements/icici_sample.pdf",
    "data/statements/icici_sample_2.pdf",
    "data/statements/icici_sample_3.pdf",
    "data/statements/icici_sample_4.pdf",
]


def _reconciles(actual: float, expected: "float | None", tolerance: float = 0.01) -> bool:
    return expected is not None and abs(actual - expected) < tolerance


pytestmark = pytest.mark.skipif(not PASSWORD, reason="ICICI_SAMPLE_PASSWORD not set in .env")


@pytest.mark.parametrize("pdf_path", SAMPLES)
def test_real_statement_period_extracted(pdf_path):
    if not Path(pdf_path).exists():
        pytest.skip(f"{pdf_path} not present locally")

    parsed = icici_dispatch.parse(pdf_path, PASSWORD, card_type="Coral")

    assert parsed["period_start"] is not None
    assert parsed["period_end"] is not None
    assert parsed["period_start"] <= parsed["period_end"]


@pytest.mark.parametrize("pdf_path", SAMPLES)
def test_real_statement_reconciles(pdf_path):
    if not Path(pdf_path).exists():
        pytest.skip(f"{pdf_path} not present locally")

    parsed = icici_dispatch.parse(pdf_path, PASSWORD, card_type="Coral")
    transactions = parsed["transactions"]
    summary = extract_summary(pdf_path, PASSWORD)

    assert len(transactions) > 0
    assert all(t["type"] in ("debit", "credit") for t in transactions)

    debit_total = sum(t["amount"] for t in transactions if t["type"] == "debit")
    credit_total = sum(t["amount"] for t in transactions if t["type"] == "credit")

    assert _reconciles(debit_total, summary["purchases_charges"]), "debit total does not reconcile"
    assert _reconciles(
        credit_total, summary["payments_credits"]
    ), "credit total does not reconcile"
