import sqlite3
from datetime import date

import pytest

from storage.cards import create_card
from storage.categories import TransactionNotFoundError, assign_category, suggest_category
from storage.db import get_connection, init_db
from storage.writes import insert_statement

# All bank names, merchants, and amounts below are fabricated for testing.


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setenv("DB_PATH", str(path))
    init_db()
    return str(path)


def _txn(day, description, month=1):
    return {
        "txn_date": date(2026, month, day),
        "description": description,
        "amount": 10.0,
        "txn_type": "debit",
        "reward_points": None,
    }


def _seed(conn, descriptions):
    """One card, one statement, one transaction per description.

    Returns transaction ids in the same order as `descriptions`, so tests
    can reason about "higher id == inserted later".
    """
    card_id = create_card(conn, "FAKE BANK", "FAKE CARD TYPE")
    insert_statement(
        conn,
        card_id,
        date(2026, 1, 1),
        date(2026, 1, 31),
        [_txn(1 + i, d) for i, d in enumerate(descriptions)],
    )
    rows = conn.execute("SELECT id FROM transactions ORDER BY id").fetchall()
    return [row["id"] for row in rows]


def _categories(conn, ids):
    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT id, category FROM transactions WHERE id IN ({placeholders}) ORDER BY id", ids
    ).fetchall()
    return [row["category"] for row in rows]


# --- migration -------------------------------------------------------------


def test_fresh_db_has_nullable_category_column(db_path):
    conn = get_connection()
    try:
        cols = {row["name"]: row for row in conn.execute("PRAGMA table_xinfo(transactions)")}
        assert "category" in cols
        assert cols["category"]["type"] == "TEXT"
        assert cols["category"]["notnull"] == 0
    finally:
        conn.close()


def test_new_transactions_default_to_null_category(db_path):
    conn = get_connection()
    try:
        ids = _seed(conn, ["A", "B"])
        assert _categories(conn, ids) == [None, None]
    finally:
        conn.close()


def test_category_migration_is_idempotent_and_preserves_existing_rows(tmp_path, monkeypatch):
    # Same technique as the statement_month migration test: build the
    # pre-migration schema by hand (here: post-Session-26, pre-category, so
    # statement_month exists but category does not) so init_db() has a real
    # "existing DB from an earlier session" to migrate.
    path = tmp_path / "legacy.db"
    monkeypatch.setenv("DB_PATH", str(path))

    legacy = sqlite3.connect(str(path))
    legacy.execute(
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
    legacy.execute(
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
    legacy.execute(
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
    legacy.execute("INSERT INTO cards (bank, card_type) VALUES ('FAKE BANK', 'FAKE CARD TYPE')")
    legacy.execute(
        "INSERT INTO statements (card_id, period_start, period_end) VALUES (1, '2026-01-01', '2026-01-31')"
    )
    legacy.execute(
        "INSERT INTO transactions (statement_id, txn_date, description, amount, txn_type) "
        "VALUES (1, '2026-01-05', 'LEGACY ROW', 10.0, 'debit')"
    )
    legacy.commit()
    legacy.close()

    init_db()
    init_db()  # must not raise on an already-migrated DB

    conn = get_connection()
    try:
        cols = {row["name"] for row in conn.execute("PRAGMA table_xinfo(transactions)")}
        assert "category" in cols
        # The statement_month migration still runs too -- both are applied.
        assert "statement_month" in {
            row["name"] for row in conn.execute("PRAGMA table_xinfo(statements)")
        }
        row = conn.execute("SELECT description, category FROM transactions").fetchone()
        assert row["description"] == "LEGACY ROW"
        assert row["category"] is None
    finally:
        conn.close()


# --- assign_category -------------------------------------------------------


def test_assign_single_and_bulk_overwrite_unconditionally(db_path):
    conn = get_connection()
    try:
        a, b, c = _seed(conn, ["A", "B", "C"])

        assert assign_category(conn, [a], "Food") == 1
        assert _categories(conn, [a, b, c]) == ["Food", None, None]

        # Bulk, including an already-categorized row: overwritten, not skipped.
        assert assign_category(conn, [a, b], "Travel") == 2
        assert _categories(conn, [a, b, c]) == ["Travel", "Travel", None]
    finally:
        conn.close()


def test_assign_duplicate_ids_count_once(db_path):
    conn = get_connection()
    try:
        (a,) = _seed(conn, ["A"])
        assert assign_category(conn, [a, a, a], "Food") == 1
    finally:
        conn.close()


def test_assign_with_any_missing_id_writes_nothing(db_path):
    conn = get_connection()
    try:
        a, b = _seed(conn, ["A", "B"])
        with pytest.raises(TransactionNotFoundError) as exc_info:
            assign_category(conn, [a, b, 9999], "Food")
        assert exc_info.value.missing_ids == [9999]
        # Atomic: the two valid ids were not updated either.
        assert _categories(conn, [a, b]) == [None, None]
    finally:
        conn.close()


def test_assign_rejects_empty_category_and_empty_id_list(db_path):
    conn = get_connection()
    try:
        (a,) = _seed(conn, ["A"])
        with pytest.raises(ValueError):
            assign_category(conn, [a], "")
        with pytest.raises(ValueError):
            assign_category(conn, [], "Food")
        assert _categories(conn, [a]) == [None]
    finally:
        conn.close()


# --- suggest_category ------------------------------------------------------


def test_cold_start_returns_no_suggestion(db_path):
    conn = get_connection()
    try:
        a, _b = _seed(conn, ["A", "B"])
        assert suggest_category(conn, a) == {
            "category": None,
            "confidence": 0.0,
            "match_type": "none",
        }
    finally:
        conn.close()


def test_unknown_transaction_raises(db_path):
    conn = get_connection()
    try:
        with pytest.raises(TransactionNotFoundError):
            suggest_category(conn, 9999)
    finally:
        conn.close()


def test_exact_tier_is_case_insensitive_and_unanimous_is_confidence_one(db_path):
    conn = get_connection()
    try:
        target, m1, m2 = _seed(conn, ["Coffee Shop", "COFFEE SHOP", "coffee shop"])
        assign_category(conn, [m1, m2], "Food")
        assert suggest_category(conn, target) == {
            "category": "Food",
            "confidence": 1.0,
            "match_type": "exact",
        }
    finally:
        conn.close()


def test_exact_tier_does_no_other_normalization(db_path):
    # Trailing whitespace and a digit difference are NOT collapsed -- decided,
    # not an oversight. These fall through to the fuzzy tier.
    conn = get_connection()
    try:
        target, spaced, digit = _seed(conn, ["SHOP 1", "SHOP 1 ", "SHOP 2"])
        assign_category(conn, [spaced, digit], "Food")
        assert suggest_category(conn, target)["match_type"] == "fuzzy"
    finally:
        conn.close()


def test_exact_tier_never_matches_the_transaction_against_itself(db_path):
    conn = get_connection()
    try:
        target, other = _seed(conn, ["SHOP", "SOMETHING ELSE"])
        assign_category(conn, [target], "Food")
        assign_category(conn, [other], "Travel")
        # The only exact match for "SHOP" is the target itself, which is
        # excluded -- so this must fall through to fuzzy and find "Travel".
        result = suggest_category(conn, target)
        assert result["match_type"] == "fuzzy"
        assert result["category"] == "Travel"
    finally:
        conn.close()


def test_exact_tier_majority_wins_with_share_as_confidence(db_path):
    conn = get_connection()
    try:
        target, f1, f2, t1 = _seed(conn, ["SHOP", "SHOP", "SHOP", "SHOP"])
        assign_category(conn, [f1, f2], "Food")
        assign_category(conn, [t1], "Travel")
        result = suggest_category(conn, target)
        assert result["category"] == "Food"
        assert result["confidence"] == pytest.approx(2 / 3)
        assert result["match_type"] == "exact"
    finally:
        conn.close()


def test_exact_tier_tie_breaks_to_highest_id(db_path):
    # "Most recently assigned" has no timestamp in the schema; highest id
    # (most recently imported) is the documented proxy.
    conn = get_connection()
    try:
        target, older, newer = _seed(conn, ["SHOP", "SHOP", "SHOP"])
        assign_category(conn, [older], "Travel")
        assign_category(conn, [newer], "Food")
        result = suggest_category(conn, target)
        assert result["category"] == "Food"
        assert result["confidence"] == pytest.approx(0.5)

        # Flip the assignments: the tie must follow the id, not the category name.
        assign_category(conn, [older], "Food")
        assign_category(conn, [newer], "Travel")
        assert suggest_category(conn, target)["category"] == "Travel"
    finally:
        conn.close()


def test_fuzzy_tier_picks_highest_ratio_and_reports_it(db_path):
    conn = get_connection()
    try:
        target, close, far = _seed(conn, ["COFFEE SHOP 12", "COFFEE SHOP 34", "AIRLINE TICKETS"])
        assign_category(conn, [close], "Food")
        assign_category(conn, [far], "Travel")
        result = suggest_category(conn, target)
        assert result["match_type"] == "fuzzy"
        assert result["category"] == "Food"
        assert 0.0 < result["confidence"] < 1.0
    finally:
        conn.close()


def test_fuzzy_tier_has_no_floor(db_path):
    conn = get_connection()
    try:
        target, only = _seed(conn, ["ZZZZZZZZ", "AAAAAAAA"])
        assign_category(conn, [only], "Travel")
        result = suggest_category(conn, target)
        assert result["match_type"] == "fuzzy"
        assert result["category"] == "Travel"
        assert result["confidence"] == 0.0
    finally:
        conn.close()


def test_fuzzy_tier_is_global_across_cards(db_path):
    conn = get_connection()
    try:
        card_a = create_card(conn, "FAKE BANK A", "FAKE CARD TYPE")
        card_b = create_card(conn, "FAKE BANK B", "FAKE CARD TYPE")
        insert_statement(conn, card_a, date(2026, 1, 1), date(2026, 1, 31), [_txn(1, "SHOP X")])
        insert_statement(conn, card_b, date(2026, 1, 1), date(2026, 1, 31), [_txn(1, "SHOP Y")])
        a_id, b_id = [r["id"] for r in conn.execute("SELECT id FROM transactions ORDER BY id")]
        assign_category(conn, [b_id], "Food")
        assert suggest_category(conn, a_id)["category"] == "Food"
    finally:
        conn.close()
