import sqlite3
from datetime import date

import pytest

from storage.cards import create_card
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


def _create_fake_card(conn, bank="FAKE BANK", card_type="FAKE CARD TYPE", nickname=None):
    return create_card(conn, bank, card_type, nickname)


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
        card_id = _create_fake_card(conn)

        conn.execute(
            "INSERT INTO statements (card_id, period_start, period_end) VALUES (?, ?, ?)",
            (card_id, "2026-01-01", "2026-01-31"),
        )
        conn.commit()

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO statements (card_id, period_start, period_end) VALUES (?, ?, ?)",
                (card_id, "2026-01-01", "2026-01-31"),
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
        card_id = _create_fake_card(conn)

        cursor = conn.execute(
            "INSERT INTO statements (card_id, period_start, period_end) VALUES (?, ?, ?)",
            (card_id, "2026-02-01", "2026-02-28"),
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


def test_cascade_delete_from_card_removes_statements_and_transactions(db_path):
    conn = get_connection()
    try:
        card_id = _create_fake_card(conn)
        statement_id = insert_statement(
            conn, card_id, date(2026, 3, 1), date(2026, 3, 31), _fake_transactions(2)
        )

        conn.execute("DELETE FROM cards WHERE id = ?", (card_id,))
        conn.commit()

        remaining_statements = conn.execute(
            "SELECT COUNT(*) AS count FROM statements WHERE card_id = ?", (card_id,)
        ).fetchone()
        remaining_transactions = conn.execute(
            "SELECT COUNT(*) AS count FROM transactions WHERE statement_id = ?",
            (statement_id,),
        ).fetchone()

        assert remaining_statements["count"] == 0
        assert remaining_transactions["count"] == 0
    finally:
        conn.close()


def test_insert_statement_persists_transactions(db_path):
    conn = get_connection()
    try:
        card_id = _create_fake_card(conn)
        statement_id = insert_statement(
            conn, card_id, date(2026, 1, 1), date(2026, 1, 31), _fake_transactions(3)
        )

        assert isinstance(statement_id, int)

        statements = conn.execute("SELECT * FROM statements").fetchall()
        transactions = conn.execute(
            "SELECT * FROM transactions WHERE statement_id = ?", (statement_id,)
        ).fetchall()

        assert len(statements) == 1
        assert statements[0]["card_id"] == card_id
        assert len(transactions) == 3
        assert all(t["statement_id"] == statement_id for t in transactions)
    finally:
        conn.close()


def test_insert_statement_dedup_returns_none_and_leaves_rows_untouched(db_path):
    conn = get_connection()
    try:
        card_id = _create_fake_card(conn)
        first_id = insert_statement(
            conn, card_id, date(2026, 1, 1), date(2026, 1, 31), _fake_transactions(3)
        )
        result = insert_statement(
            conn,
            card_id,
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


def test_insert_statement_same_card_different_periods_both_succeed(db_path):
    conn = get_connection()
    try:
        card_id = _create_fake_card(conn)
        id_one = insert_statement(
            conn, card_id, date(2026, 1, 1), date(2026, 1, 31), _fake_transactions(1)
        )
        id_two = insert_statement(
            conn, card_id, date(2026, 2, 1), date(2026, 2, 28), _fake_transactions(1)
        )

        assert id_one is not None
        assert id_two is not None
        assert id_one != id_two
    finally:
        conn.close()


def test_insert_statement_same_period_different_cards_both_succeed(db_path):
    conn = get_connection()
    try:
        card_one = _create_fake_card(conn, bank="FAKE BANK A")
        card_two = _create_fake_card(conn, bank="FAKE BANK B")

        id_one = insert_statement(
            conn, card_one, date(2026, 1, 1), date(2026, 1, 31), _fake_transactions(1)
        )
        id_two = insert_statement(
            conn, card_two, date(2026, 1, 1), date(2026, 1, 31), _fake_transactions(1)
        )

        assert id_one is not None
        assert id_two is not None
        assert id_one != id_two
    finally:
        conn.close()


def test_insert_statement_missing_card_id_raises_integrity_error(db_path):
    conn = get_connection()
    try:
        with pytest.raises(sqlite3.IntegrityError):
            insert_statement(conn, 9999, date(2026, 1, 1), date(2026, 1, 31), _fake_transactions(1))
    finally:
        conn.close()


def test_insert_statement_malformed_transaction_rolls_back_atomically(db_path):
    conn = get_connection()
    try:
        card_id = _create_fake_card(conn)
        transactions = _fake_transactions(3)
        transactions[1]["amount"] = None  # violates NOT NULL

        result = insert_statement(
            conn, card_id, date(2026, 1, 1), date(2026, 1, 31), transactions
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
        card_id = _create_fake_card(conn)
        statement_id = insert_statement(
            conn, card_id, date(2026, 1, 1), date(2026, 1, 31), _fake_transactions(1)
        )

        row = conn.execute(
            "SELECT reward_points FROM transactions WHERE statement_id = ?", (statement_id,)
        ).fetchone()

        assert row["reward_points"] is None
    finally:
        conn.close()


def test_statement_month_populates_on_insert(db_path):
    conn = get_connection()
    try:
        card_id = _create_fake_card(conn)
        insert_statement(
            conn, card_id, date(2026, 6, 17), date(2026, 7, 16), _fake_transactions(1)
        )

        row = conn.execute(
            "SELECT statement_month FROM statements WHERE card_id = ?", (card_id,)
        ).fetchone()

        assert row["statement_month"] == "July-2026"
    finally:
        conn.close()


def test_statement_month_migration_is_idempotent_and_backfills_existing_rows(tmp_path, monkeypatch):
    # Deliberately bypasses storage.db entirely to build a pre-Session-26
    # schema (no statement_month column) exactly as an earlier session would
    # have left it on disk, rather than reusing the db_path fixture -- which
    # already runs the current (migrated) init_db() and so could never
    # reproduce the "existing DB from an earlier session" scenario this test
    # exists to cover.
    path = tmp_path / "legacy.db"
    monkeypatch.setenv("DB_PATH", str(path))

    legacy_conn = sqlite3.connect(str(path))
    legacy_conn.execute(
        """
        CREATE TABLE cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bank TEXT NOT NULL,
            card_type TEXT NOT NULL,
            nickname TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(bank, card_type, nickname)
        )
        """
    )
    legacy_conn.execute(
        """
        CREATE TABLE statements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            card_id INTEGER NOT NULL,
            period_start DATE NOT NULL,
            period_end DATE NOT NULL,
            imported_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(card_id) REFERENCES cards(id) ON DELETE CASCADE,
            UNIQUE(card_id, period_start, period_end)
        )
        """
    )
    legacy_conn.execute(
        """
        CREATE TABLE transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            statement_id INTEGER NOT NULL,
            txn_date DATE NOT NULL,
            description TEXT NOT NULL,
            amount REAL NOT NULL,
            txn_type TEXT NOT NULL,
            reward_points REAL,
            FOREIGN KEY(statement_id) REFERENCES statements(id) ON DELETE CASCADE
        )
        """
    )
    legacy_conn.execute("INSERT INTO cards (bank, card_type) VALUES ('FAKE BANK', 'FAKE CARD TYPE')")
    legacy_conn.commit()
    card_id = legacy_conn.execute("SELECT id FROM cards").fetchone()[0]
    legacy_conn.execute(
        "INSERT INTO statements (card_id, period_start, period_end) VALUES (?, ?, ?)",
        (card_id, "2025-12-17", "2026-01-16"),
    )
    legacy_conn.commit()
    legacy_conn.close()

    init_db()
    init_db()  # must not raise -- idempotency against an already-migrated DB too

    conn = get_connection()
    try:
        pre_existing = conn.execute(
            "SELECT statement_month FROM statements WHERE card_id = ?", (card_id,)
        ).fetchone()
        assert pre_existing["statement_month"] == "January-2026"

        new_statement_id = insert_statement(
            conn, card_id, date(2026, 2, 1), date(2026, 2, 28), _fake_transactions(1)
        )
        new_row = conn.execute(
            "SELECT statement_month FROM statements WHERE id = ?", (new_statement_id,)
        ).fetchone()
        assert new_row["statement_month"] == "February-2026"
    finally:
        conn.close()
