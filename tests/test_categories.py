import sqlite3
from datetime import date

import pytest

from storage.cards import create_card
from storage import categories
from storage.categories import (
    TransactionNotFoundError,
    assign_categories,
    cluster_by_similarity,
    cluster_transactions,
    fuzzy_similarity,
    list_categories,
    list_merchants,
    list_subcategories,
    suggest_categories,
    suggest_category,
)
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


def _assign(conn, ids, category):
    """Uniform category assignment: N triples with the same category, no subcategory."""
    return assign_categories(conn, [(i, category, None, None, None) for i in ids])


def _cat(result):
    """The category half of a Session 53 suggestion result."""
    return result["category"]


def _merchants(conn, ids):
    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT id, merchant FROM transactions WHERE id IN ({placeholders}) ORDER BY id", ids
    ).fetchall()
    return [row["merchant"] for row in rows]


def _subcategories(conn, ids):
    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT id, subcategory FROM transactions WHERE id IN ({placeholders}) ORDER BY id", ids
    ).fetchall()
    return [row["subcategory"] for row in rows]


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
        assert "subcategory" in cols
        assert cols["subcategory"]["type"] == "TEXT"
        assert cols["subcategory"]["notnull"] == 0
        assert "merchant" in cols
        assert cols["merchant"]["type"] == "TEXT"
        assert cols["merchant"]["notnull"] == 0
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
        assert "subcategory" in cols  # Session 53 migration, same idiom
        assert "merchant" in cols  # Session 55, same idiom again
        # The statement_month migration still runs too -- all are applied.
        assert "statement_month" in {
            row["name"] for row in conn.execute("PRAGMA table_xinfo(statements)")
        }
        row = conn.execute(
            "SELECT description, category, subcategory, merchant FROM transactions"
        ).fetchone()
        assert row["description"] == "LEGACY ROW"
        assert row["category"] is None
        assert row["subcategory"] is None
        assert row["merchant"] is None
    finally:
        conn.close()


# --- assign_categories -----------------------------------------------------


def test_assign_single_and_bulk_overwrite_unconditionally(db_path):
    conn = get_connection()
    try:
        a, b, c = _seed(conn, ["A", "B", "C"])

        assert assign_categories(conn, [(a, "Food", None, None, None)]) == 1
        assert _categories(conn, [a, b, c]) == ["Food", None, None]

        # Bulk, including an already-categorized row: overwritten, not skipped.
        assert assign_categories(conn, [(a, "Travel", None, None, None), (b, "Travel", None, None, None)]) == 2
        assert _categories(conn, [a, b, c]) == ["Travel", "Travel", None]
    finally:
        conn.close()


def test_assign_mixed_categories_in_one_call(db_path):
    # The reason for the pairs shape: one call, each row its own value.
    conn = get_connection()
    try:
        a, b, c = _seed(conn, ["A", "B", "C"])
        assert assign_categories(conn, [(a, "Food", None, None, None), (b, "Travel", None, None, None), (c, "Food", None, None, None)]) == 3
        assert _categories(conn, [a, b, c]) == ["Food", "Travel", "Food"]
    finally:
        conn.close()


def test_assign_identical_duplicate_pairs_count_once(db_path):
    conn = get_connection()
    try:
        (a,) = _seed(conn, ["A"])
        assert assign_categories(conn, [(a, "Food", None, None, None), (a, "Food", None, None, None), (a, "Food", None, None, None)]) == 1
    finally:
        conn.close()


def test_assign_conflicting_duplicate_pairs_are_rejected_and_write_nothing(db_path):
    conn = get_connection()
    try:
        a, b = _seed(conn, ["A", "B"])
        with pytest.raises(ValueError):
            assign_categories(conn, [(a, "Food", None, None, None), (b, "Travel", None, None, None), (a, "Travel", None, None, None)])
        assert _categories(conn, [a, b]) == [None, None]
    finally:
        conn.close()


def test_assign_with_any_missing_id_writes_nothing(db_path):
    conn = get_connection()
    try:
        a, b = _seed(conn, ["A", "B"])
        with pytest.raises(TransactionNotFoundError) as exc_info:
            # Mixed categories: the existence check must cover every group, not just one.
            assign_categories(conn, [(a, "Food", None, None, None), (b, "Travel", None, None, None), (9999, "Food", None, None, None)])
        assert exc_info.value.missing_ids == [9999]
        # Atomic: the two valid ids were not updated either.
        assert _categories(conn, [a, b]) == [None, None]
    finally:
        conn.close()


def test_assign_rejects_empty_category_and_empty_pair_list(db_path):
    conn = get_connection()
    try:
        (a,) = _seed(conn, ["A"])
        with pytest.raises(ValueError):
            assign_categories(conn, [(a, "", None, None, None)])
        with pytest.raises(ValueError):
            assign_categories(conn, [])
        assert _categories(conn, [a]) == [None]
    finally:
        conn.close()


# --- suggest_category ------------------------------------------------------


def test_cold_start_returns_no_suggestion(db_path):
    conn = get_connection()
    try:
        a, _b = _seed(conn, ["A", "B"])
        result = suggest_category(conn, a)
        assert _cat(result) == {"value": None, "confidence": 0.0, "match_type": "none"}
        # Category unset on the row -> no subcategory suggestion at all.
        assert result["subcategory"] is None
        # Merchant is never absent: true cold start falls to the description.
        assert result["merchant"] == {
            "value": "A",
            "confidence": None,
            "match_type": "from_description",
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
        _assign(conn, [m1, m2], "Food")
        assert _cat(suggest_category(conn, target)) == {
            "value": "Food",
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
        _assign(conn, [spaced, digit], "Food")
        assert _cat(suggest_category(conn, target))["match_type"] == "fuzzy"
    finally:
        conn.close()


def test_exact_tier_never_matches_the_transaction_against_itself(db_path):
    conn = get_connection()
    try:
        target, other = _seed(conn, ["SHOP", "SOMETHING ELSE"])
        _assign(conn, [target], "Food")
        _assign(conn, [other], "Travel")
        # The only exact match for "SHOP" is the target itself, which is
        # excluded -- so this must fall through to fuzzy and find "Travel".
        result = _cat(suggest_category(conn, target))
        assert result["match_type"] == "fuzzy"
        assert result["value"] == "Travel"
    finally:
        conn.close()


def test_exact_tier_majority_wins_with_share_as_confidence(db_path):
    conn = get_connection()
    try:
        target, f1, f2, t1 = _seed(conn, ["SHOP", "SHOP", "SHOP", "SHOP"])
        _assign(conn, [f1, f2], "Food")
        _assign(conn, [t1], "Travel")
        result = _cat(suggest_category(conn, target))
        assert result["value"] == "Food"
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
        _assign(conn, [older], "Travel")
        _assign(conn, [newer], "Food")
        result = _cat(suggest_category(conn, target))
        assert result["value"] == "Food"
        assert result["confidence"] == pytest.approx(0.5)

        # Flip the assignments: the tie must follow the id, not the category name.
        _assign(conn, [older], "Food")
        _assign(conn, [newer], "Travel")
        assert _cat(suggest_category(conn, target))["value"] == "Travel"
    finally:
        conn.close()


def test_fuzzy_tier_picks_highest_ratio_and_reports_it(db_path):
    conn = get_connection()
    try:
        target, close, far = _seed(conn, ["COFFEE SHOP 12", "COFFEE SHOP 34", "AIRLINE TICKETS"])
        _assign(conn, [close], "Food")
        _assign(conn, [far], "Travel")
        result = _cat(suggest_category(conn, target))
        assert result["match_type"] == "fuzzy"
        assert result["value"] == "Food"
        assert 0.0 < result["confidence"] < 1.0
    finally:
        conn.close()


def test_fuzzy_tier_has_no_floor(db_path):
    conn = get_connection()
    try:
        target, only = _seed(conn, ["ZZZZZZZZ", "AAAAAAAA"])
        _assign(conn, [only], "Travel")
        result = _cat(suggest_category(conn, target))
        assert result["match_type"] == "fuzzy"
        assert result["value"] == "Travel"
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
        _assign(conn, [b_id], "Food")
        assert _cat(suggest_category(conn, a_id))["value"] == "Food"
    finally:
        conn.close()


# --- suggest_categories (batch) --------------------------------------------


def test_batch_matches_single_id_results_in_input_order(db_path):
    conn = get_connection()
    try:
        t1, t2, t3, m = _seed(conn, ["SHOP", "AIRLINE", "ZZZZ", "shop"])
        _assign(conn, [m], "Food")
        ids = [t3, t1, t2]
        batch = suggest_categories(conn, ids)
        assert [b["transaction_id"] for b in batch] == ids
        for entry in batch:
            expected = suggest_category(conn, entry["transaction_id"])
            assert {k: v for k, v in entry.items() if k != "transaction_id"} == expected
        assert batch[1]["category"]["match_type"] == "exact"
    finally:
        conn.close()


def test_batch_runs_the_categorized_query_once(db_path, monkeypatch):
    conn = get_connection()
    try:
        ids = _seed(conn, ["A", "B", "C", "D", "E"])
        _assign(conn, ids[-1:], "Food")

        calls = []
        real = categories._fetch_labeled

        def counting(c):
            calls.append(1)
            return real(c)

        monkeypatch.setattr(categories, "_fetch_labeled", counting)
        result = suggest_categories(conn, ids)
        assert len(result) == len(ids)
        assert len(calls) == 1
    finally:
        conn.close()


def test_batch_excludes_each_target_from_its_own_candidates(db_path):
    # Two categorized rows batched together: each must see only the other.
    conn = get_connection()
    try:
        a, b = _seed(conn, ["SHOP", "SOMETHING ELSE"])
        _assign(conn, [a], "Food")
        _assign(conn, [b], "Travel")
        by_id = {e["transaction_id"]: e for e in suggest_categories(conn, [a, b])}
        assert by_id[a]["category"]["value"] == "Travel"
        assert by_id[b]["category"]["value"] == "Food"
    finally:
        conn.close()


def test_batch_cold_start_and_duplicates(db_path):
    conn = get_connection()
    try:
        a, b = _seed(conn, ["A", "B"])
        result = suggest_categories(conn, [a, a, b])
        assert [e["transaction_id"] for e in result] == [a, b]
        assert all(e["category"]["match_type"] == "none" for e in result)
        assert all(e["subcategory"] is None for e in result)
    finally:
        conn.close()


def test_batch_with_any_missing_id_raises_and_computes_nothing(db_path, monkeypatch):
    conn = get_connection()
    try:
        (a,) = _seed(conn, ["A"])
        monkeypatch.setattr(
            categories, "_fetch_labeled", lambda c: pytest.fail("engine ran")
        )
        with pytest.raises(TransactionNotFoundError) as exc_info:
            suggest_categories(conn, [a, 9999])
        assert exc_info.value.missing_ids == [9999]
        with pytest.raises(ValueError):
            suggest_categories(conn, [])
    finally:
        conn.close()


# --- list_categories -------------------------------------------------------


def test_list_categories_is_sorted_distinct_and_empty_before_any_assignment(db_path):
    conn = get_connection()
    try:
        a, b, c, d = _seed(conn, ["A", "B", "C", "D"])
        assert list_categories(conn) == []
        assign_categories(conn, [(a, "Travel", None, None, None), (b, "Food", None, None, None), (c, "Food", None, None, None)])
        assert list_categories(conn) == ["Food", "Travel"]
        # Reassigning the only "Travel" row drops it from the catalog.
        assign_categories(conn, [(a, "Food", None, None, None)])
        assert list_categories(conn) == ["Food"]
    finally:
        conn.close()


# --- fuzzy_similarity (shared comparison) -----------------------------------


@pytest.mark.parametrize(
    "a, b",
    [
        ("COFFEE SHOP 12", "COFFEE SHOP 34"),
        ("coffee shop 12", "COFFEE SHOP 12"),
        ("ZZZZZZZZ", "AAAAAAAA"),
        ("SHOP 1", "SHOP 1 "),
        ("", "ANYTHING"),
    ],
)
def test_fuzzy_similarity_is_exactly_tier_twos_inline_formula(a, b):
    # The extraction must not move Tier 2 by a single ulp: the shared
    # function is SequenceMatcher(None, a.casefold(), b.casefold()).ratio(),
    # which is what Session 41 wrote inline.
    from difflib import SequenceMatcher

    assert fuzzy_similarity(a, b) == SequenceMatcher(None, a.casefold(), b.casefold()).ratio()
    # Idempotent under pre-casefolded input, which is how Tier 2 calls it.
    assert fuzzy_similarity(a.casefold(), b) == fuzzy_similarity(a, b)


def test_fuzzy_similarity_bounds_and_case_insensitivity():
    assert fuzzy_similarity("Shop", "SHOP") == 1.0
    assert fuzzy_similarity("ZZZZ", "AAAA") == 0.0
    assert 0.0 < fuzzy_similarity("COFFEE SHOP 12", "COFFEE SHOP 34") < 1.0


def test_tier_two_confidence_equals_shared_function(db_path):
    # End to end: the engine's reported confidence is the shared function's
    # value for the winning pair, so the two cannot drift apart.
    conn = get_connection()
    try:
        target, close, far = _seed(conn, ["COFFEE SHOP 12", "COFFEE SHOP 34", "AIRLINE TICKETS"])
        _assign(conn, [close], "Food")
        _assign(conn, [far], "Travel")
        result = _cat(suggest_category(conn, target))
        assert result["confidence"] == fuzzy_similarity("COFFEE SHOP 12", "COFFEE SHOP 34")
    finally:
        conn.close()


# --- cluster_by_similarity ----------------------------------------------------


def _ids_of(clusters):
    """Membership view of the rich cluster shape: [[anchor, member, ...], ...]."""
    return [[m["transaction_id"] for m in c["members"]] for c in clusters]


def test_clustering_reports_anchor_and_per_member_similarity():
    # "abcd" vs "abce" is exactly 0.75; the member's reported similarity is
    # that same admitting comparison, as a 0-100 value; the anchor is 100.
    items = [(1, "abcd"), (2, "abce"), (3, "abcd")]
    clusters = cluster_by_similarity(items, 70)
    assert clusters == [
        {
            "anchor_id": 1,
            "members": [
                {"transaction_id": 1, "similarity": 100.0},
                {"transaction_id": 2, "similarity": 75.0},
                {"transaction_id": 3, "similarity": 100.0},
            ],
        }
    ]
    for c in clusters:
        assert c["members"][0]["transaction_id"] == c["anchor_id"]
        assert all(0.0 <= m["similarity"] <= 100.0 for m in c["members"])


def test_clustering_produces_multiple_clusters_in_anchor_order():
    items = [
        (1, "COFFEE SHOP 12"),
        (2, "AIRLINE TICKETS 88"),
        (3, "COFFEE SHOP 34"),
        (4, "AIRLINE TICKETS 99"),
        (5, "COFFEE SHOP 56"),
        (6, "SOMETHING UNRELATED ZZZ"),
    ]
    assert _ids_of(cluster_by_similarity(items, 70)) == [[1, 3, 5], [2, 4]]


def test_clustering_everything_in_one_cluster():
    items = [(10, "SHOP A"), (11, "SHOP B"), (12, "SHOP C")]
    assert _ids_of(cluster_by_similarity(items, 60)) == [[10, 11, 12]]
    # Threshold 0 admits everything, whatever the descriptions.
    assert _ids_of(cluster_by_similarity([(1, "AAAA"), (2, "ZZZZ")], 0)) == [[1, 2]]


def test_clustering_all_singletons_returns_no_clusters():
    items = [(1, "AAAA"), (2, "BBBB"), (3, "CCCC")]
    assert cluster_by_similarity(items, 70) == []
    # 100 requires identity (after casefolding).
    assert _ids_of(cluster_by_similarity([(1, "SHOP"), (2, "SHOP "), (3, "shop")], 100)) == [[1, 3]]
    assert cluster_by_similarity([], 70) == []
    assert cluster_by_similarity([(1, "ONLY")], 0) == []


def test_clustering_threshold_boundary_is_inclusive():
    # "abcd" vs "abce": 3 matching of 8 total chars -> ratio exactly 0.75.
    assert fuzzy_similarity("abcd", "abce") == 0.75
    items = [(1, "abcd"), (2, "abce")]
    assert _ids_of(cluster_by_similarity(items, 75)) == [[1, 2]]
    assert cluster_by_similarity(items, 76) == []


def test_clustering_is_anchor_based_not_transitive_and_respects_order():
    # B is close to A and to C, but A and C are far apart. Anchored on A,
    # B joins A and C is left alone as a singleton (dropped) -- membership is
    # decided against the anchor only. Reordering changes the outcome, which
    # is why the input order is honoured rather than re-sorted.
    a, b, c = (1, "AAAAAAAAXXXX"), (2, "AAAAXXXXCCCC"), (3, "XXXXCCCCCCCC")
    assert fuzzy_similarity(a[1], b[1]) >= 0.6
    assert fuzzy_similarity(b[1], c[1]) >= 0.6
    assert fuzzy_similarity(a[1], c[1]) < 0.6
    assert _ids_of(cluster_by_similarity([a, b, c], 60)) == [[1, 2]]
    assert _ids_of(cluster_by_similarity([b, a, c], 60)) == [[2, 1, 3]]


def test_clustering_collapses_duplicate_ids():
    assert _ids_of(cluster_by_similarity([(1, "SHOP A"), (1, "SHOP A"), (2, "SHOP B")], 60)) == [[1, 2]]


def test_cluster_transactions_resolves_descriptions_and_404s(db_path):
    conn = get_connection()
    try:
        a, b, c = _seed(conn, ["COFFEE SHOP 12", "AIRLINE TICKETS", "COFFEE SHOP 34"])
        assert _ids_of(cluster_transactions(conn, [a, b, c], 70)) == [[a, c]]
        assert cluster_transactions(conn, [], 70) == []
        with pytest.raises(TransactionNotFoundError):
            cluster_transactions(conn, [a, 9999], 70)
    finally:
        conn.close()


# --- subcategory: assignment ---------------------------------------------------


def test_assign_subcategory_only_leaves_category_untouched(db_path):
    conn = get_connection()
    try:
        a, b = _seed(conn, ["A", "B"])
        assign_categories(conn, [(a, "Food", None, None, None)])
        assert assign_categories(conn, [(a, None, "Coffee", None, None)]) == 1
        assert _categories(conn, [a, b]) == ["Food", None]
        assert _subcategories(conn, [a, b]) == ["Coffee", None]
        # Subcategory can be set on a row with no category; the API allows it
        # and storage does not second-guess.
        assign_categories(conn, [(b, None, "Misc", None, None)])
        assert _categories(conn, [a, b]) == ["Food", None]
        assert _subcategories(conn, [a, b]) == ["Coffee", "Misc"]
    finally:
        conn.close()


def test_assign_category_only_leaves_subcategory_untouched(db_path):
    conn = get_connection()
    try:
        (a,) = _seed(conn, ["A"])
        assign_categories(conn, [(a, "Food", "Coffee", None, None)])
        assert assign_categories(conn, [(a, "Travel", None, None, None)]) == 1
        assert _categories(conn, [a]) == ["Travel"]
        assert _subcategories(conn, [a]) == ["Coffee"]
    finally:
        conn.close()


def test_assign_both_together_and_merged_fields_for_one_id(db_path):
    conn = get_connection()
    try:
        a, b = _seed(conn, ["A", "B"])
        assert assign_categories(conn, [(a, "Food", "Coffee", None, None), (b, "Food", "Tea", None, None)]) == 2
        assert _categories(conn, [a, b]) == ["Food", "Food"]
        assert _subcategories(conn, [a, b]) == ["Coffee", "Tea"]
        # Two triples for one id setting different fields merge into one update.
        assert assign_categories(conn, [(a, "Travel", None, None, None), (a, None, "Flights", None, None)]) == 1
        assert _categories(conn, [a]) == ["Travel"]
        assert _subcategories(conn, [a]) == ["Flights"]
    finally:
        conn.close()


def test_assign_rejects_neither_field_and_conflicting_subcategories(db_path):
    conn = get_connection()
    try:
        (a,) = _seed(conn, ["A"])
        with pytest.raises(ValueError):
            assign_categories(conn, [(a, None, None, None, None)])
        with pytest.raises(ValueError):
            assign_categories(conn, [(a, None, "", None, None)])
        with pytest.raises(ValueError):
            assign_categories(conn, [(a, None, "Coffee", None, None), (a, None, "Tea", None, None)])
        assert _categories(conn, [a]) == [None]
        assert _subcategories(conn, [a]) == [None]
    finally:
        conn.close()


# --- subcategory: suggestion --------------------------------------------------


def test_subcategory_suggestion_is_none_until_category_is_set(db_path):
    conn = get_connection()
    try:
        target, peer = _seed(conn, ["SHOP", "SHOP"])
        assign_categories(conn, [(peer, "Food", "Snacks", None, None)])
        result = suggest_category(conn, target)
        # Category is suggested (exact peer) but subcategory does not run.
        assert _cat(result)["value"] == "Food"
        assert result["subcategory"] is None
    finally:
        conn.close()


def test_subcategory_exact_match_same_category_and_description(db_path):
    conn = get_connection()
    try:
        target, p1, p2, other_cat, other_desc = _seed(
            conn, ["Coffee Shop", "COFFEE SHOP", "coffee shop", "COFFEE SHOP", "TEA HOUSE"]
        )
        assign_categories(conn, [(target, "Food", None, None, None)])
        assign_categories(conn, [(p1, "Food", "Cafe", None, None), (p2, "Food", "Cafe", None, None)])
        # Same description but a different category: not a peer.
        assign_categories(conn, [(other_cat, "Travel", "Airport", None, None)])
        # Same category and a subcategory but a different description: not a peer.
        assign_categories(conn, [(other_desc, "Food", "Tea", None, None)])
        assert suggest_category(conn, target)["subcategory"] == {
            "value": "Cafe",
            "confidence": 1.0,
            "match_type": "exact",
        }
    finally:
        conn.close()


def test_subcategory_falls_back_to_same_as_category(db_path):
    conn = get_connection()
    try:
        target, near, other = _seed(conn, ["COFFEE SHOP 12", "COFFEE SHOP 34", "COFFEE SHOP 12"])
        assign_categories(conn, [(target, "Food", None, None, None)])
        # A fuzzy neighbour with a subcategory does NOT count: no fuzzy tier.
        assign_categories(conn, [(near, "Food", "Cafe", None, None)])
        # An exact-description peer in the same category but with no
        # subcategory does not count either.
        assign_categories(conn, [(other, "Food", None, None, None)])
        assert suggest_category(conn, target)["subcategory"] == {
            "value": "Food",
            "confidence": 1.0,
            "match_type": "same_as_category",
        }
    finally:
        conn.close()


def test_subcategory_majority_wins_and_ties_break_to_highest_id(db_path):
    conn = get_connection()
    try:
        target, a1, a2, b1 = _seed(conn, ["SHOP", "SHOP", "SHOP", "SHOP"])
        assign_categories(conn, [(target, "Food", None, None, None)])
        assign_categories(
            conn,
            [(a1, "Food", "Cafe", None, None), (a2, "Food", "Cafe", None, None), (b1, "Food", "Bakery", None, None)],
        )
        result = suggest_category(conn, target)["subcategory"]
        assert result["value"] == "Cafe"
        assert result["confidence"] == pytest.approx(2 / 3)
        assert result["match_type"] == "exact"
    finally:
        conn.close()


def test_subcategory_tie_breaks_to_highest_id(db_path):
    # Same proxy as category Tier 1: no assignment timestamp exists, so a
    # 1-1 split goes to the peer with the higher id (most recently imported).
    conn = get_connection()
    try:
        target, older, newer = _seed(conn, ["SHOP", "SHOP", "SHOP"])
        assign_categories(conn, [(target, "Food", None, None, None)])
        assign_categories(conn, [(older, "Food", "Bakery", None, None), (newer, "Food", "Cafe", None, None)])
        result = suggest_category(conn, target)["subcategory"]
        assert result["value"] == "Cafe"
        assert result["confidence"] == pytest.approx(0.5)

        # Flip the values: the tie must follow the id, not the name.
        assign_categories(conn, [(older, None, "Cafe", None, None), (newer, None, "Bakery", None, None)])
        assert suggest_category(conn, target)["subcategory"]["value"] == "Bakery"
    finally:
        conn.close()


def test_subcategory_category_match_is_case_insensitive_and_self_excluded(db_path):
    conn = get_connection()
    try:
        target, peer = _seed(conn, ["SHOP", "SHOP"])
        # Storage does not normalise; write mixed case directly to prove the
        # comparison itself is case-insensitive.
        assign_categories(conn, [(target, "food", "Own", None, None), (peer, "FOOD", "Cafe", None, None)])
        result = suggest_category(conn, target)["subcategory"]
        assert result == {"value": "Cafe", "confidence": 1.0, "match_type": "exact"}
        # The target's own subcategory never suggests itself back.
        conn.execute("UPDATE transactions SET subcategory = NULL WHERE id = ?", (peer,))
        conn.commit()
        assert suggest_category(conn, target)["subcategory"]["match_type"] == "same_as_category"
    finally:
        conn.close()


def test_batch_carries_subcategory_suggestions(db_path):
    conn = get_connection()
    try:
        a, b, c = _seed(conn, ["SHOP", "SHOP", "OTHER"])
        assign_categories(conn, [(a, "Food", None, None, None), (b, "Food", "Cafe", None, None)])
        by_id = {e["transaction_id"]: e for e in suggest_categories(conn, [a, b, c])}
        assert by_id[a]["subcategory"] == {"value": "Cafe", "confidence": 1.0, "match_type": "exact"}
        assert by_id[b]["subcategory"]["match_type"] == "same_as_category"
        assert by_id[c]["subcategory"] is None
    finally:
        conn.close()


# --- subcategory: merchant_category precedent tier (Session 88) -----------------


def _seed_typed(conn, rows):
    """Like _seed but each entry is (description, txn_type); ids in order."""
    card_id = create_card(conn, "FAKE BANK", "FAKE CARD TYPE")
    txns = []
    for i, (d, t) in enumerate(rows):
        txn = _txn(1 + i, d)
        txn["txn_type"] = t
        txns.append(txn)
    insert_statement(conn, card_id, date(2026, 1, 1), date(2026, 1, 31), txns)
    return [row["id"] for row in conn.execute("SELECT id FROM transactions ORDER BY id").fetchall()]


def _label(conn, txn_id, category, subcategory, merchant):
    assign_categories(conn, [(txn_id, category, subcategory, merchant, None)])


def test_subcategory_merchant_category_tier_fires_and_falls_back(db_path):
    conn = get_connection()
    try:
        # Descriptions all differ: no exact-description peer exists anywhere,
        # so Tier 1 is out of the picture and only the precedent tier can fire.
        target, p1, p2, wrong_cat, wrong_merchant, no_sub = _seed(
            conn, ["AMZ ORDER 1", "AMZ ORDER 2", "AMZ ORDER 3", "AMZ ORDER 4", "AMZ ORDER 5", "AMZ ORDER 6"]
        )
        _label(conn, target, "Grocery", None, "Amazon")
        _label(conn, p1, "Grocery", "Household", "Amazon")
        _label(conn, p2, "Grocery", "Household", "Amazon")
        # Same merchant, different category: not a precedent.
        _label(conn, wrong_cat, "Shopping", "Electronics", "Amazon")
        # Same category, different merchant: not a precedent.
        _label(conn, wrong_merchant, "Grocery", "Vegetables", "Bigbasket")
        # Same merchant and category but no subcategory: not a precedent.
        _label(conn, no_sub, "Grocery", None, "Amazon")
        assert suggest_category(conn, target)["subcategory"] == {
            "value": "Household",
            "confidence": 1.0,
            "match_type": "merchant_category",
            "precedents": 2,
        }

        # Remove the precedents' subcategories: back to same_as_category,
        # exactly the pre-Session-88 shape (no "precedents" key).
        conn.execute("UPDATE transactions SET subcategory = NULL WHERE id IN (?, ?)", (p1, p2))
        conn.commit()
        assert suggest_category(conn, target)["subcategory"] == {
            "value": "Grocery",
            "confidence": 1.0,
            "match_type": "same_as_category",
        }
    finally:
        conn.close()


def test_subcategory_merchant_category_requires_merchant_on_target(db_path):
    conn = get_connection()
    try:
        target, p1 = _seed(conn, ["AMZ ORDER 1", "AMZ ORDER 2"])
        _label(conn, target, "Grocery", None, None)
        _label(conn, p1, "Grocery", "Household", "Amazon")
        # No merchant on the target -> nothing to match on -> fallback.
        assert suggest_category(conn, target)["subcategory"]["match_type"] == "same_as_category"
    finally:
        conn.close()


def test_subcategory_exact_description_outranks_merchant_category(db_path):
    conn = get_connection()
    try:
        target, exact_peer, precedent = _seed(conn, ["AMZ ORDER 1", "amz order 1", "AMZ ORDER 2"])
        _label(conn, target, "Grocery", None, "Amazon")
        _label(conn, exact_peer, "Grocery", "Snacks", "Amazon")
        _label(conn, precedent, "Grocery", "Household", "Amazon")
        result = suggest_category(conn, target)["subcategory"]
        assert result["match_type"] == "exact"
        assert result["value"] == "Snacks"
    finally:
        conn.close()


def test_subcategory_merchant_category_majority_wins_then_highest_id(db_path):
    conn = get_connection()
    try:
        target, a1, b1, a2, b2, b3 = _seed(
            conn, ["AMZ 1", "AMZ 2", "AMZ 3", "AMZ 4", "AMZ 5", "AMZ 6"]
        )
        _label(conn, target, "Grocery", None, "Amazon")
        for i in (a1, a2):
            _label(conn, i, "Grocery", "Household", "Amazon")
        for i in (b1, b2, b3):
            _label(conn, i, "Grocery", "Snacks", "Amazon")
        result = suggest_category(conn, target)["subcategory"]
        assert result["value"] == "Snacks"
        assert result["confidence"] == pytest.approx(3 / 5)
        assert result["precedents"] == 5

        # Drop one Snacks precedent so it is 2-2: the value on the highest id
        # wins. b2 > a2 in id order, so Snacks; then flip b3's value so the
        # highest-id row is Household and the tie goes the other way.
        conn.execute("UPDATE transactions SET subcategory = NULL WHERE id = ?", (b3,))
        conn.commit()
        tied = suggest_category(conn, target)["subcategory"]
        assert tied["value"] == "Snacks"
        assert tied["confidence"] == pytest.approx(0.5)
        assert tied["precedents"] == 4
        _label(conn, b3, None, "Household", None)
        # Now Household 3 : Snacks 2 -- majority, not id, decides.
        assert suggest_category(conn, target)["subcategory"]["value"] == "Household"
        _label(conn, b3, None, "Snacks", None)
        _label(conn, b2, None, "Household", None)
        # Household on {a1, a2, b2}, Snacks on {b1, b3}: 3-2 again but with
        # the highest id on the minority -- majority still wins.
        assert suggest_category(conn, target)["subcategory"]["value"] == "Household"
    finally:
        conn.close()


def test_subcategory_merchant_category_tie_breaks_to_highest_id(db_path):
    conn = get_connection()
    try:
        target, older, newer = _seed(conn, ["AMZ 1", "AMZ 2", "AMZ 3"])
        _label(conn, target, "Grocery", None, "Amazon")
        _label(conn, older, "Grocery", "Household", "Amazon")
        _label(conn, newer, "Grocery", "Snacks", "Amazon")
        assert suggest_category(conn, target)["subcategory"]["value"] == "Snacks"
        # Flip: the tie follows the id, not the name.
        _label(conn, older, None, "Snacks", None)
        _label(conn, newer, None, "Household", None)
        assert suggest_category(conn, target)["subcategory"]["value"] == "Household"
    finally:
        conn.close()


def test_subcategory_merchant_category_counts_credit_and_cascade_rows(db_path):
    # A precedent qualifies on its three columns alone: a credit (refund)
    # row counts, and so does a row whose labels were set by the is_payment
    # cascade rather than by hand. (Review status is not a separate
    # dimension: a row with merchant + category + subcategory is by
    # definition "complete" under Session 80's derived status.)
    conn = get_connection()
    try:
        target, refund, payment = _seed_typed(
            conn, [("AMZ 1", "debit"), ("AMZ REFUND", "credit"), ("PAYMENT RECEIVED", "credit")]
        )
        _label(conn, target, "Grocery", None, "Amazon")
        _label(conn, refund, "Grocery", "Household", "Amazon")
        result = suggest_category(conn, target)["subcategory"]
        assert result == {
            "value": "Household",
            "confidence": 1.0,
            "match_type": "merchant_category",
            "precedents": 1,
        }

        # Cascade-set labels: is_payment=True writes category = subcategory =
        # PAYMENT_LABEL and merchant = the card's bank name ("FAKE BANK").
        assign_categories(conn, [(payment, None, None, None, True)])
        target2 = _seed(conn, ["AMZ 1"])[-1]  # a fresh row, new card, same DB
        _label(conn, target2, categories.PAYMENT_LABEL, None, "Fake Bank")
        result = suggest_category(conn, target2)["subcategory"]
        # Merchant comparison is case-insensitive: the cascade stored
        # "FAKE BANK", the manual write Title-Cased "Fake Bank".
        assert result["match_type"] == "merchant_category"
        assert result["value"] == categories.PAYMENT_LABEL
        assert result["precedents"] == 1
    finally:
        conn.close()


def test_batch_carries_merchant_category_suggestions(db_path):
    conn = get_connection()
    try:
        a, b = _seed(conn, ["AMZ 1", "AMZ 2"])
        _label(conn, a, "Grocery", None, "Amazon")
        _label(conn, b, "Grocery", "Household", "Amazon")
        by_id = {e["transaction_id"]: e for e in suggest_categories(conn, [a, b])}
        assert by_id[a]["subcategory"]["match_type"] == "merchant_category"
        assert by_id[a]["subcategory"]["value"] == "Household"
        # b's only possible precedent is a, which has no subcategory.
        assert by_id[b]["subcategory"]["match_type"] == "same_as_category"
    finally:
        conn.close()


# --- list_subcategories -------------------------------------------------------


def test_list_subcategories_unfiltered_and_filtered(db_path):
    conn = get_connection()
    try:
        a, b, c, d = _seed(conn, ["A", "B", "C", "D"])
        assert list_subcategories(conn) == []
        assign_categories(
            conn,
            [
                (a, "Food", "Tea", None, None),
                (b, "Food", "Cafe", None, None),
                (c, "Travel", "Flights", None, None),
                (d, "Food", None, None, None),
            ],
        )
        assert list_subcategories(conn) == ["Cafe", "Flights", "Tea"]
        assert list_subcategories(conn, category="Food") == ["Cafe", "Tea"]
        assert list_subcategories(conn, category="Travel") == ["Flights"]
        assert list_subcategories(conn, category="Nothing") == []
    finally:
        conn.close()


# --- merchant (Session 55) ---------------------------------------------------


def test_assign_merchant_only_and_combinations(db_path):
    conn = get_connection()
    try:
        a, b, c = _seed(conn, ["A", "B", "C"])
        assert assign_categories(conn, [(a, None, None, "Shop One", None)]) == 1
        assert _categories(conn, [a]) == [None]
        assert _merchants(conn, [a]) == ["Shop One"]
        # merchant + category
        assert assign_categories(conn, [(b, "Food", None, "Shop Two", None)]) == 1
        assert (_categories(conn, [b]), _subcategories(conn, [b]), _merchants(conn, [b])) == (
            ["Food"], [None], ["Shop Two"]
        )
        # merchant + subcategory
        assert assign_categories(conn, [(c, None, "Cafe", "Shop Three", None)]) == 1
        assert (_categories(conn, [c]), _subcategories(conn, [c]), _merchants(conn, [c])) == (
            [None], ["Cafe"], ["Shop Three"]
        )
        # all three, overwriting; then a category-only write leaves merchant alone
        assert assign_categories(conn, [(a, "Travel", "Flights", "Shop Nine", None)]) == 1
        assign_categories(conn, [(a, "Food", None, None, None)])
        assert (_categories(conn, [a]), _subcategories(conn, [a]), _merchants(conn, [a])) == (
            ["Food"], ["Flights"], ["Shop Nine"]
        )
        # conflicting merchants for one id -> rejected, nothing written
        with pytest.raises(ValueError):
            assign_categories(conn, [(b, None, None, "X", None), (b, None, None, "Y", None)])
        assert _merchants(conn, [b]) == ["Shop Two"]
    finally:
        conn.close()


def test_merchant_cold_start_falls_back_to_description(db_path):
    conn = get_connection()
    try:
        # Other rows have categories but nobody has a merchant: still Tier 3.
        target, other = _seed(conn, ["Coffee Shop 12", "COFFEE SHOP 12"])
        _assign(conn, [other], "Food")
        assert suggest_category(conn, target)["merchant"] == {
            "value": "Coffee Shop 12",
            "confidence": None,
            "match_type": "from_description",
        }
    finally:
        conn.close()


def test_merchant_exact_tier_majority_and_tie_break(db_path):
    conn = get_connection()
    try:
        target, m1, m2, m3, other = _seed(conn, ["SHOP", "shop", "Shop", "SHOP", "ELSEWHERE"])
        assign_categories(
            conn,
            [(m1, None, None, "Alpha", None), (m2, None, None, "Alpha", None), (m3, None, None, "Beta", None),
             (other, None, None, "Gamma", None)],
        )
        result = suggest_category(conn, target)["merchant"]
        assert result == {"value": "Alpha", "confidence": pytest.approx(2 / 3), "match_type": "exact"}

        # 1-1 tie -> highest id wins, whichever value it holds.
        assign_categories(conn, [(m2, None, None, "Beta", None)])  # Alpha: m1 ; Beta: m2, m3
        assign_categories(conn, [(m3, None, None, "Alpha", None)])  # Alpha: m1, m3 ; Beta: m2 -> majority Alpha
        conn.execute("UPDATE transactions SET merchant = NULL WHERE id = ?", (m1,))
        conn.commit()
        # Now Alpha: m3 ; Beta: m2 -> tie, m3 is the higher id.
        assert suggest_category(conn, target)["merchant"]["value"] == "Alpha"
        assign_categories(conn, [(m2, None, None, "Alpha", None), (m3, None, None, "Beta", None)])
        assert suggest_category(conn, target)["merchant"]["value"] == "Beta"
    finally:
        conn.close()


def test_merchant_fuzzy_tier_is_global_and_not_scoped_by_category(db_path):
    conn = get_connection()
    try:
        target, close, far = _seed(conn, ["COFFEE SHOP 12", "COFFEE SHOP 34", "AIRLINE TICKETS"])
        # Different categories everywhere: irrelevant to merchant matching.
        assign_categories(conn, [(target, "Travel", None, None, None)])
        assign_categories(conn, [(close, "Food", None, "Bean Bar", None), (far, "Travel", None, "Sky Air", None)])
        result = suggest_category(conn, target)["merchant"]
        assert result["match_type"] == "fuzzy"
        assert result["value"] == "Bean Bar"
        assert result["confidence"] == fuzzy_similarity("COFFEE SHOP 12", "COFFEE SHOP 34")
    finally:
        conn.close()


def test_merchant_never_matches_itself(db_path):
    conn = get_connection()
    try:
        (only,) = _seed(conn, ["SHOP"])
        assign_categories(conn, [(only, None, None, "Alpha", None)])
        # The only merchant-bearing row is the target: cold start for it.
        assert suggest_category(conn, only)["merchant"]["match_type"] == "from_description"
    finally:
        conn.close()


def test_batch_carries_merchant_and_runs_one_query(db_path, monkeypatch):
    conn = get_connection()
    try:
        a, b, c = _seed(conn, ["SHOP", "SHOP", "OTHER"])
        assign_categories(conn, [(b, None, None, "Alpha", None)])
        calls = []
        real = categories._fetch_labeled
        monkeypatch.setattr(categories, "_fetch_labeled", lambda cn: (calls.append(1), real(cn))[1])
        by_id = {e["transaction_id"]: e for e in suggest_categories(conn, [a, b, c])}
        assert len(calls) == 1
        assert by_id[a]["merchant"] == {"value": "Alpha", "confidence": 1.0, "match_type": "exact"}
        assert by_id[b]["merchant"]["match_type"] == "from_description"  # self excluded
        assert by_id[c]["merchant"]["match_type"] == "fuzzy"
    finally:
        conn.close()


def test_list_merchants_is_sorted_distinct_and_unscoped(db_path):
    conn = get_connection()
    try:
        a, b, c = _seed(conn, ["A", "B", "C"])
        assert list_merchants(conn) == []
        assign_categories(
            conn, [(a, "Food", None, "Zeta", None), (b, "Travel", None, "Alpha", None), (c, None, None, "Alpha", None)]
        )
        assert list_merchants(conn) == ["Alpha", "Zeta"]
    finally:
        conn.close()
