import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

import parsers.icici as icici_dispatch
from storage.adapters import from_parsed_statement
from storage.cards import create_card
from storage.db import get_connection, init_db
from storage.writes import insert_statement

# End-to-end integration test: real sample PDFs, through the full
# parse -> adapt -> insert_statement pipeline, into an isolated tmp_path DB.
# Skips cleanly if .env/ICICI_SAMPLE_PASSWORD or the sample files aren't
# present locally, matching the pattern in test_integration_import.py.
# Only counts, ids, and statement periods are asserted on or would appear in
# failure output -- never amounts, merchants, or individual transaction dates.
#
# This is the ICICI half of the Session 30 generalization check: the pipeline
# below is byte-for-byte the HDFC one with a different dispatch module and
# card_type, which is the evidence that the adapter and storage layers are
# genuinely bank-agnostic rather than HDFC-shaped by coincidence.

load_dotenv()

PASSWORD = os.environ.get("ICICI_SAMPLE_PASSWORD")

SAMPLE_PATHS = [
    "data/statements/icici_sample.pdf",
    "data/statements/icici_sample_2.pdf",
    "data/statements/icici_sample_3.pdf",
    "data/statements/icici_sample_4.pdf",
]

pytestmark = pytest.mark.skipif(not PASSWORD, reason="ICICI_SAMPLE_PASSWORD not set in .env")


@pytest.fixture
def card_id(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    init_db()

    conn = get_connection()
    try:
        new_card_id = create_card(conn, "ICICI", "Coral")
    finally:
        conn.close()

    return new_card_id


def _import(pdf_path, card_id):
    conn = get_connection()
    try:
        parsed = icici_dispatch.parse(pdf_path, PASSWORD, card_type="Coral")
        insert_args = from_parsed_statement(parsed, card_id=card_id)
        statement_id = insert_statement(conn, *insert_args)
        return statement_id, parsed
    finally:
        conn.close()


def test_import_all_real_samples_succeed_with_matching_transaction_counts(card_id):
    available_samples = [p for p in SAMPLE_PATHS if Path(p).exists()]
    if not available_samples:
        pytest.skip("no sample statements present locally")

    statement_ids = []

    for pdf_path in available_samples:
        statement_id, parsed = _import(pdf_path, card_id)

        assert statement_id is not None, (
            f"import unexpectedly failed for period "
            f"{parsed['period_start']}..{parsed['period_end']}"
        )
        statement_ids.append(statement_id)

        conn = get_connection()
        try:
            row_count = conn.execute(
                "SELECT COUNT(*) AS count FROM transactions WHERE statement_id = ?",
                (statement_id,),
            ).fetchone()["count"]
        finally:
            conn.close()

        assert row_count == len(parsed["transactions"]), (
            f"stored transaction count ({row_count}) does not match parser "
            f"output ({len(parsed['transactions'])}) for period "
            f"{parsed['period_start']}..{parsed['period_end']}"
        )

    # No false dedup collisions across genuinely different statement periods.
    assert len(set(statement_ids)) == len(statement_ids)


def test_reimporting_same_samples_dedups(card_id):
    available_samples = [p for p in SAMPLE_PATHS if Path(p).exists()]
    if not available_samples:
        pytest.skip("no sample statements present locally")

    for pdf_path in available_samples:
        first_id, _ = _import(pdf_path, card_id)
        assert first_id is not None

        second_id, parsed = _import(pdf_path, card_id)
        assert second_id is None, (
            f"expected dedup skip on re-import for period "
            f"{parsed['period_start']}..{parsed['period_end']}"
        )
