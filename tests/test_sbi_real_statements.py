import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

import parsers.sbi as sbi_dispatch
from parsers.sbi.sbi_titan import extract_summary

# These tests run the parser against the real sample statement PDFs in
# data/statements/ (git-ignored, not part of the repo) using the real password
# from .env (also git-ignored). They skip automatically if either isn't present
# locally, so the suite still passes for anyone who clones the repo without
# them. Only reconciliation results and counts are asserted on -- never real
# amounts, dates, or merchant descriptions.
#
# parse() goes through the parsers.sbi dispatch layer (card_type="Titan") so
# the dispatch path itself is exercised, not just the Titan implementation
# directly. extract_summary() is Titan-specific reconciliation tooling, not
# part of the dispatch interface, so it's imported straight from
# parsers.sbi.sbi_titan.
#
# Session 32 committed only sbi_sample.pdf; Session 33 widened this to all four
# samples, matching the HDFC (Session 15) and ICICI (Session 29) suites. Two of
# the four continue the transaction table onto page 2, so these also stand as
# the regression guard on multi-page scanning.
#
# Like the ICICI suite and unlike HDFC's, there is no layout-detection test:
# SBI Titan has a single known statement layout, so parsers/sbi/sbi_titan.py
# has no _detect_layout() counterpart to assert on.

load_dotenv()

PASSWORD = os.environ.get("SBI_SAMPLE_PASSWORD")

SAMPLES = [
    "data/statements/sbi_sample.pdf",
    "data/statements/sbi_sample_2.pdf",
    "data/statements/sbi_sample_3.pdf",
    "data/statements/sbi_sample_4.pdf",
]


def _reconciles(actual: float, expected: "float | None", tolerance: float = 0.01) -> bool:
    return expected is not None and abs(actual - expected) < tolerance


pytestmark = pytest.mark.skipif(not PASSWORD, reason="SBI_SAMPLE_PASSWORD not set in .env")


@pytest.mark.parametrize("pdf_path", SAMPLES)
def test_real_statement_period_extracted(pdf_path):
    if not Path(pdf_path).exists():
        pytest.skip(f"{pdf_path} not present locally")

    parsed = sbi_dispatch.parse(pdf_path, PASSWORD, card_type="Titan")

    assert parsed["period_start"] is not None
    assert parsed["period_end"] is not None
    assert parsed["period_start"] <= parsed["period_end"]


@pytest.mark.parametrize("pdf_path", SAMPLES)
def test_real_statement_transactions_well_formed(pdf_path):
    if not Path(pdf_path).exists():
        pytest.skip(f"{pdf_path} not present locally")

    parsed = sbi_dispatch.parse(pdf_path, PASSWORD, card_type="Titan")
    transactions = parsed["transactions"]

    assert len(transactions) > 0
    assert all(t["type"] in ("debit", "credit") for t in transactions)


@pytest.mark.parametrize("pdf_path", SAMPLES)
def test_real_statement_reconciles(pdf_path):
    if not Path(pdf_path).exists():
        pytest.skip(f"{pdf_path} not present locally")

    parsed = sbi_dispatch.parse(pdf_path, PASSWORD, card_type="Titan")
    transactions = parsed["transactions"]
    summary = extract_summary(pdf_path, PASSWORD)

    debit_total = sum(t["amount"] for t in transactions if t["type"] == "debit")
    credit_total = sum(t["amount"] for t in transactions if t["type"] == "credit")

    assert _reconciles(debit_total, summary["purchases_debits"]), "debit total does not reconcile"
    assert _reconciles(
        credit_total, summary["payments_credits"]
    ), "credit total does not reconcile"
