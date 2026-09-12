from datetime import date, datetime

import pytest

from storage.adapters import from_parsed_statement
from storage.cards import create_card
from storage.db import get_connection, init_db
from storage.writes import insert_statement

# All merchant names, amounts, and reward points below are fabricated for testing.

_FAKE_PARSED_STATEMENT = {
    "period_start": date(2026, 1, 1),
    "period_end": date(2026, 1, 31),
    "transactions": [
        {
            "date": datetime(2026, 1, 5, 14, 30),
            "description": "FAKE MERCHANT ONE",
            "amount": 250.50,
            "type": "debit",
            "reward_points": 15,
        },
        {
            "date": datetime(2026, 1, 10, 9, 0),
            "description": "FAKE PAYMENT",
            "amount": 5000.00,
            "type": "credit",
            "reward_points": None,
        },
    ],
}


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setenv("DB_PATH", str(path))
    init_db()
    return str(path)


def test_from_parsed_statement_returns_correctly_shaped_tuple():
    card_id, period_start, period_end, transactions = from_parsed_statement(
        _FAKE_PARSED_STATEMENT, card_id=42
    )

    assert card_id == 42
    assert period_start == date(2026, 1, 1)
    assert period_end == date(2026, 1, 31)
    assert len(transactions) == 2


def test_from_parsed_statement_maps_field_names_correctly():
    _, _, _, transactions = from_parsed_statement(_FAKE_PARSED_STATEMENT, card_id=1)
    txn = transactions[0]

    assert set(txn.keys()) == {
        "txn_date", "description", "amount", "txn_type", "reward_points", "is_payment"
    }
    # Absent on the parser side -> False on the storage side, never missing.
    assert txn["is_payment"] is False
    assert txn["txn_date"] == date(2026, 1, 5)  # time-of-day dropped
    assert txn["description"] == "FAKE MERCHANT ONE"
    assert txn["amount"] == 250.50
    assert txn["txn_type"] == "debit"
    assert txn["reward_points"] == 15


def test_from_parsed_statement_reward_points_none_passes_through():
    _, _, _, transactions = from_parsed_statement(_FAKE_PARSED_STATEMENT, card_id=1)

    assert transactions[1]["reward_points"] is None
    assert transactions[1]["txn_type"] == "credit"


def test_from_parsed_statement_round_trip_through_insert_statement(db_path):
    conn = get_connection()
    try:
        card_id = create_card(conn, "FAKE BANK", "FAKE CARD TYPE")

        args = from_parsed_statement(_FAKE_PARSED_STATEMENT, card_id=card_id)
        statement_id = insert_statement(conn, *args)

        assert statement_id is not None

        stored_statement = conn.execute(
            "SELECT * FROM statements WHERE id = ?", (statement_id,)
        ).fetchone()
        stored_transactions = conn.execute(
            "SELECT * FROM transactions WHERE statement_id = ? ORDER BY txn_date",
            (statement_id,),
        ).fetchall()

        assert stored_statement["card_id"] == card_id
        assert stored_statement["period_start"] == "2026-01-01"
        assert stored_statement["period_end"] == "2026-01-31"
        assert len(stored_transactions) == 2
        assert stored_transactions[0]["description"] == "FAKE MERCHANT ONE"
        assert stored_transactions[0]["txn_type"] == "debit"
        assert stored_transactions[0]["reward_points"] == 15
        assert stored_transactions[1]["description"] == "FAKE PAYMENT"
        assert stored_transactions[1]["txn_type"] == "credit"
        assert stored_transactions[1]["reward_points"] is None
    finally:
        conn.close()
