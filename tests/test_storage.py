import sqlite3
from datetime import date

import pytest

from storage.db import get_connection, init_db
from storage.writes import insert_statement

# All bank names, merchants, and amounts below are fabricated for testing.


def _fake_transactions(n=3):
    return [
        {
            "txn_date": date(2026, 1, i + 1),
            "description": f"FAKE MERCHANT {i}",
            "amount": 10.0 * (i + 1),
            "txn_type": "debit",
            "reward_points": None,
        }
        for i in range(n)
    ]


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setenv("DB_PATH", str(path))
    init_db()
    return str(path)


def _table_names(conn):
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {row["name"] for row in rows}


def test_statements_table_exists_after_init(db_path):
    conn = get_connection()
    try:
        assert "statements" in _table_names(conn)
    finally:
        conn.close()


def test_transactions_table_exists_after_init(db_path):
    conn = get_connection()
    try:
        assert "transactions" in _table_names(conn)
    finally:
        conn.close()


def test_init_db_is_idempotent(db_path):
    init_db()  # calling again must not raise


def test_duplicate_statement_raises_integrity_error(db_path):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO statements (bank, period_start, period_end) VALUES (?, ?, ?)",
            ("FAKE BANK", "2026-01-01", "2026-01-31"),
        )
        conn.commit()

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO statements (bank, period_start, period_end) VALUES (?, ?, ?)",
                ("FAKE BANK", "2026-01-01", "2026-01-31"),
            )
    finally:
        conn.close()


def test_transaction_with_missing_statement_raises_integrity_error(db_path):
    conn = get_connection()
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO transactions "
                "(statement_id, txn_date, description, amount, txn_type) "
                "VALUES (?, ?, ?, ?, ?)",
                (9999, "2026-01-05", "FAKE MERCHANT", 100.0, "debit"),
            )
    finally:
        conn.close()


def test_cascade_delete_removes_transactions(db_path):
    conn = get_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO statements (bank, period_start, period_end) VALUES (?, ?, ?)",
            ("FAKE BANK", "2026-02-01", "2026-02-28"),
        )
        statement_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO transactions "
            "(statement_id, txn_date, description, amount, txn_type) "
            "VALUES (?, ?, ?, ?, ?)",
            (statement_id, "2026-02-05", "FAKE MERCHANT", 50.0, "debit"),
        )
        conn.commit()

        conn.execute("DELETE FROM statements WHERE id = ?", (statement_id,))
        conn.commit()

        remaining = conn.execute(
            "SELECT COUNT(*) AS count FROM transactions WHERE statement_id = ?",
            (statement_id,),
        ).fetchone()
        assert remaining["count"] == 0
    finally:
        conn.close()


def test_insert_statement_persists_transactions(db_path):
    conn = get_connection()
    try:
        statement_id = insert_statement(
            conn, "FAKE BANK", date(2026, 1, 1), date(2026, 1, 31), _fake_transactions(3)
        )

        assert isinstance(statement_id, int)

        statements = conn.execute("SELECT * FROM statements").fetchall()
        transactions = conn.execute(
            "SELECT * FROM transactions WHERE statement_id = ?", (statement_id,)
        ).fetchall()

        assert len(statements) == 1
        assert len(transactions) == 3
        assert all(t["statement_id"] == statement_id for t in transactions)
    finally:
        conn.close()


def test_insert_statement_dedup_returns_none_and_leaves_rows_untouched(db_path):
    conn = get_connection()
    try:
        first_id = insert_statement(
            conn, "FAKE BANK", date(2026, 1, 1), date(2026, 1, 31), _fake_transactions(3)
        )
        result = insert_statement(
            conn,
            "FAKE BANK",
            date(2026, 1, 1),
            date(2026, 1, 31),
            _fake_transactions(5),  # deliberately different, must be ignored
        )

        assert result is None

        statements = conn.execute("SELECT * FROM statements").fetchall()
        transactions = conn.execute(
            "SELECT * FROM transactions WHERE statement_id = ?", (first_id,)
        ).fetchall()

        assert len(statements) == 1
        assert len(transactions) == 3
    finally:
        conn.close()


def test_insert_statement_same_bank_different_periods_both_succeed(db_path):
    conn = get_connection()
    try:
        id_one = insert_statement(
            conn, "FAKE BANK", date(2026, 1, 1), date(2026, 1, 31), _fake_transactions(1)
        )
        id_two = insert_statement(
            conn, "FAKE BANK", date(2026, 2, 1), date(2026, 2, 28), _fake_transactions(1)
        )

        assert id_one is not None
        assert id_two is not None
        assert id_one != id_two
    finally:
        conn.close()


def test_insert_statement_same_period_different_banks_both_succeed(db_path):
    conn = get_connection()
    try:
        id_one = insert_statement(
            conn, "FAKE BANK A", date(2026, 1, 1), date(2026, 1, 31), _fake_transactions(1)
        )
        id_two = insert_statement(
            conn, "FAKE BANK B", date(2026, 1, 1), date(2026, 1, 31), _fake_transactions(1)
        )

        assert id_one is not None
        assert id_two is not None
        assert id_one != id_two
    finally:
        conn.close()


def test_insert_statement_malformed_transaction_rolls_back_atomically(db_path):
    conn = get_connection()
    try:
        transactions = _fake_transactions(3)
        transactions[1]["amount"] = None  # violates NOT NULL

        result = insert_statement(
            conn, "FAKE BANK", date(2026, 1, 1), date(2026, 1, 31), transactions
        )

        assert result is None

        statements = conn.execute("SELECT * FROM statements").fetchall()
        transactions_in_db = conn.execute("SELECT * FROM transactions").fetchall()

        assert len(statements) == 0
        assert len(transactions_in_db) == 0
    finally:
        conn.close()


def test_insert_statement_reward_points_none_stored_as_null(db_path):
    conn = get_connection()
    try:
        statement_id = insert_statement(
            conn, "FAKE BANK", date(2026, 1, 1), date(2026, 1, 31), _fake_transactions(1)
        )

        row = conn.execute(
            "SELECT reward_points FROM transactions WHERE statement_id = ?", (statement_id,)
        ).fetchone()

        assert row["reward_points"] is None
    finally:
        conn.close()
