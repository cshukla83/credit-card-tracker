import sqlite3

import pytest

from storage.db import get_connection, init_db

# All bank names, merchants, and amounts below are fabricated for testing.


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
