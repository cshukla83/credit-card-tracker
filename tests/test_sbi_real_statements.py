import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

import parsers.sbi as sbi_dispatch
from parsers.sbi.sbi_titan import extract_summary

# This test runs the parser against the real sample statement PDF in
# data/statements/ (git-ignored, not part of the repo) using the real password
# from .env (also git-ignored). It skips automatically if either isn't present
# locally, so the suite still passes for anyone who clones the repo without
# them. Only reconciliation results and counts are asserted on -- never real
# amounts, dates, or merchant descriptions.
#
# parse() goes through the parsers.sbi dispatch layer (card_type="Titan") so
# the dispatch path itself is exercised, not just the Titan implementation
# directly. extract_summary() is Titan-specific reconciliation tooling, not
# part of the dispatch interface, so it's imported straight from
# parsers.sbi.sbi_titan.

load_dotenv()

PASSWORD = os.environ.get("SBI_SAMPLE_PASSWORD")

SAMPLE = "data/statements/sbi_sample.pdf"


def _reconciles(actual: float, expected: "float | None", tolerance: float = 0.01) -> bool:
    return expected is not None and abs(actual - expected) < tolerance


pytestmark = pytest.mark.skipif(not PASSWORD, reason="SBI_SAMPLE_PASSWORD not set in .env")


def _parse():
    if not Path(SAMPLE).exists():
        pytest.skip(f"{SAMPLE} not present locally")
    return sbi_dispatch.parse(SAMPLE, PASSWORD, card_type="Titan")


def test_real_statement_period_extracted():
    parsed = _parse()

    assert parsed["period_start"] is not None
    assert parsed["period_end"] is not None
    assert parsed["period_start"] <= parsed["period_end"]


def test_real_statement_transactions_well_formed():
    parsed = _parse()
    transactions = parsed["transactions"]

    assert len(transactions) > 0
    assert all(t["type"] in ("debit", "credit") for t in transactions)


def test_real_statement_reconciles():
    parsed = _parse()
    transactions = parsed["transactions"]
    summary = extract_summary(SAMPLE, PASSWORD)

    debit_total = sum(t["amount"] for t in transactions if t["type"] == "debit")
    credit_total = sum(t["amount"] for t in transactions if t["type"] == "credit")

    assert _reconciles(debit_total, summary["purchases_debits"]), "debit total does not reconcile"
    assert _reconciles(
        credit_total, summary["payments_credits"]
    ), "credit total does not reconcile"
