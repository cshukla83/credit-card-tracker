import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

import parsers.hdfc as hdfc_dispatch
from parsers.hdfc_diners import _detect_layout, extract_summary

# These tests run the parsers against the real sample statement PDFs in
# data/statements/ (git-ignored, not part of the repo) using the real password
# from .env (also git-ignored). They skip automatically if either isn't present
# locally, so the suite still passes for anyone who clones the repo without
# them. Only reconciliation results and counts are asserted on -- never real
# amounts, dates, or merchant descriptions.
#
# parse() goes through the parsers.hdfc dispatch layer (card_type="Diners") so
# the dispatch path itself is exercised, not just the Diners implementation
# directly. extract_summary()/_detect_layout() are Diners-specific reconciliation
# tooling, not part of the dispatch interface, so those are imported straight
# from parsers.hdfc_diners.

load_dotenv()

PASSWORD = os.environ.get("HDFC_SAMPLE_PASSWORD")

SAMPLES = [
    ("data/statements/hdfc_sample.pdf", "current"),
    ("data/statements/hdfc_sample_2.pdf", "current"),
    ("data/statements/hdfc_sample_3.pdf", "current"),
    ("data/statements/hdfc_sample_4.PDF", "legacy"),
    ("data/statements/hdfc_sample_5.PDF", "legacy"),
    ("data/statements/hdfc_sample_6.pdf", "current"),
]


def _reconciles(actual: float, expected: "float | None", tolerance: float = 0.01) -> bool:
    return expected is not None and abs(actual - expected) < tolerance


pytestmark = pytest.mark.skipif(
    not PASSWORD, reason="HDFC_SAMPLE_PASSWORD not set in .env"
)


@pytest.mark.parametrize("pdf_path, expected_layout", SAMPLES)
def test_real_statement_layout_detected(pdf_path, expected_layout):
    if not Path(pdf_path).exists():
        pytest.skip(f"{pdf_path} not present locally")

    assert _detect_layout(pdf_path, PASSWORD) == expected_layout


@pytest.mark.parametrize("pdf_path, expected_layout", SAMPLES)
def test_real_statement_reconciles(pdf_path, expected_layout):
    if not Path(pdf_path).exists():
        pytest.skip(f"{pdf_path} not present locally")

    transactions = hdfc_dispatch.parse(pdf_path, PASSWORD, card_type="Diners")
    summary = extract_summary(pdf_path, PASSWORD)

    assert len(transactions) > 0
    assert all(t["type"] in ("debit", "credit") for t in transactions)

    debit_total = sum(t["amount"] for t in transactions if t["type"] == "debit")
    credit_total = sum(t["amount"] for t in transactions if t["type"] == "credit")

    assert _reconciles(debit_total, summary["purchases_debit"]), "debit total does not reconcile"
    assert _reconciles(
        credit_total, summary["payments_credits_received"]
    ), "credit total does not reconcile"
