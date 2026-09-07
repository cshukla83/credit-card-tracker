import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

import parsers.indusind as indusind_dispatch
from parsers.indusind.indusind_legend import extract_summary

# These tests run the parser against the real sample statement PDFs in
# data/statements/ (git-ignored, not part of the repo) using the real password
# from .env (also git-ignored). They skip automatically if either isn't present
# locally, so the suite still passes for anyone who clones the repo without
# them. Only reconciliation results and counts are asserted on -- never real
# amounts, dates, or merchant descriptions.
#
# parse() goes through the parsers.indusind dispatch layer (card_type="Legend")
# so the dispatch path itself is exercised, not just the Legend implementation
# directly. extract_summary() is Legend-specific reconciliation tooling, not
# part of the dispatch interface, so it's imported straight from
# parsers.indusind.indusind_legend.
#
# All four samples are covered from the outset, matching the state HDFC, ICICI
# and SBI each reached (Sessions 15, 29 and 33 respectively).
#
# Like the ICICI and SBI suites, there is no layout-detection test: all four
# IndusInd samples share a single layout, so no _detect_layout() counterpart
# exists to assert on.

load_dotenv()

PASSWORD = os.environ.get("INDUSIND_SAMPLE_PASSWORD")

SAMPLES = [
    "data/statements/IndusInd_sample.pdf",
    "data/statements/IndusInd_sample_2.pdf",
    "data/statements/IndusInd_sample_3.pdf",
    "data/statements/IndusInd_sample_4.pdf",
]


def _reconciles(actual: float, expected: "float | None", tolerance: float = 0.01) -> bool:
    return expected is not None and abs(actual - expected) < tolerance


pytestmark = pytest.mark.skipif(not PASSWORD, reason="INDUSIND_SAMPLE_PASSWORD not set in .env")


@pytest.mark.parametrize("pdf_path", SAMPLES)
def test_real_statement_period_extracted(pdf_path):
    if not Path(pdf_path).exists():
        pytest.skip(f"{pdf_path} not present locally")

    parsed = indusind_dispatch.parse(pdf_path, PASSWORD, card_type="Legend")

    assert parsed["period_start"] is not None
    assert parsed["period_end"] is not None
    assert parsed["period_start"] <= parsed["period_end"]


@pytest.mark.parametrize("pdf_path", SAMPLES)
def test_real_statement_transactions_well_formed(pdf_path):
    if not Path(pdf_path).exists():
        pytest.skip(f"{pdf_path} not present locally")

    parsed = indusind_dispatch.parse(pdf_path, PASSWORD, card_type="Legend")
    transactions = parsed["transactions"]

    assert len(transactions) > 0
    assert all(t["type"] in ("debit", "credit") for t in transactions)


@pytest.mark.parametrize("pdf_path", SAMPLES)
def test_real_statement_reconciles(pdf_path):
    if not Path(pdf_path).exists():
        pytest.skip(f"{pdf_path} not present locally")

    parsed = indusind_dispatch.parse(pdf_path, PASSWORD, card_type="Legend")
    transactions = parsed["transactions"]
    summary = extract_summary(pdf_path, PASSWORD)

    debit_total = sum(t["amount"] for t in transactions if t["type"] == "debit")
    credit_total = sum(t["amount"] for t in transactions if t["type"] == "credit")

    assert _reconciles(debit_total, summary["purchases_charges"]), "debit total does not reconcile"
    assert _reconciles(
        credit_total, summary["payments_credits"]
    ), "credit total does not reconcile"
