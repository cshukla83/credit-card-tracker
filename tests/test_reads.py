from datetime import date

import pytest

from storage.cards import create_card
from storage.db import get_connection, init_db
from storage.reads import get_transactions, list_card_types, list_statement_months
from storage.writes import insert_statement

# All bank names, merchants, and amounts below are fabricated for testing.


def _txn(day, description, amount=10.0, month=1):
    return {
        "txn_date": date(2026, month, day),
        "description": description,
        "amount": amount,
        "txn_type": "debit",
        "reward_points": None,
    }


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setenv("DB_PATH", str(path))
    init_db()
    return str(path)


@pytest.fixture
def two_cards(db_path):
    """Two cards, five transactions total, spread across January 2026:

    Card A (3 txns): Jan 5, Jan 10, Jan 15
    Card B (2 txns): Jan 8, Jan 20
    """
    conn = get_connection()
    try:
        card_a = create_card(conn, "FAKE BANK A", "FAKE CARD TYPE")
        card_b = create_card(conn, "FAKE BANK B", "FAKE CARD TYPE")

        insert_statement(
            conn,
            card_a,
            date(2026, 1, 1),
            date(2026, 1, 31),
            [
                _txn(5, "CARD A TXN 1"),
                _txn(10, "CARD A TXN 2"),
                _txn(15, "CARD A TXN 3"),
            ],
        )
        insert_statement(
            conn,
            card_b,
            date(2026, 1, 1),
            date(2026, 1, 31),
            [
                _txn(8, "CARD B TXN 1"),
                _txn(20, "CARD B TXN 2"),
            ],
        )
    finally:
        conn.close()

    return card_a, card_b


def _descriptions(rows):
    return {row["description"] for row in rows}


def test_no_filters_returns_all_transactions_across_all_cards(two_cards):
    conn = get_connection()
    try:
        rows = get_transactions(conn)
        assert len(rows) == 5
    finally:
        conn.close()


def test_card_id_only_filters_to_that_cards_transactions(two_cards):
    card_a, _card_b = two_cards
    conn = get_connection()
    try:
        rows = get_transactions(conn, card_id=card_a)
        assert _descriptions(rows) == {"CARD A TXN 1", "CARD A TXN 2", "CARD A TXN 3"}
    finally:
        conn.close()


def test_start_date_only(two_cards):
    conn = get_connection()
    try:
        rows = get_transactions(conn, start_date=date(2026, 1, 10))
        assert _descriptions(rows) == {"CARD A TXN 2", "CARD A TXN 3", "CARD B TXN 2"}
    finally:
        conn.close()


def test_end_date_only(two_cards):
    conn = get_connection()
    try:
        rows = get_transactions(conn, end_date=date(2026, 1, 10))
        assert _descriptions(rows) == {"CARD A TXN 1", "CARD B TXN 1", "CARD A TXN 2"}
    finally:
        conn.close()


def test_start_and_end_date_range(two_cards):
    conn = get_connection()
    try:
        rows = get_transactions(conn, start_date=date(2026, 1, 8), end_date=date(2026, 1, 15))
        assert _descriptions(rows) == {"CARD B TXN 1", "CARD A TXN 2", "CARD A TXN 3"}
    finally:
        conn.close()


def test_all_three_filters_combined(two_cards):
    card_a, _card_b = two_cards
    conn = get_connection()
    try:
        rows = get_transactions(
            conn, card_id=card_a, start_date=date(2026, 1, 8), end_date=date(2026, 1, 15)
        )
        assert _descriptions(rows) == {"CARD A TXN 2", "CARD A TXN 3"}
    finally:
        conn.close()


def test_boundary_dates_are_inclusive(two_cards):
    conn = get_connection()
    try:
        # start_date lands exactly on Card A Txn 1's date, end_date exactly on
        # Card B Txn 2's date -- both boundary transactions must be included,
        # not excluded by an off-by-one strict-inequality bug.
        rows = get_transactions(conn, start_date=date(2026, 1, 5), end_date=date(2026, 1, 20))
        assert len(rows) == 5
        assert "CARD A TXN 1" in _descriptions(rows)
        assert "CARD B TXN 2" in _descriptions(rows)
    finally:
        conn.close()


def test_empty_result_set_when_filters_match_nothing(two_cards):
    conn = get_connection()
    try:
        rows = get_transactions(conn, start_date=date(2026, 2, 1), end_date=date(2026, 2, 28))
        assert rows == []
    finally:
        conn.close()


def test_ordering_is_date_desc_then_id_desc_for_same_day_transactions(db_path):
    conn = get_connection()
    try:
        card_id = create_card(conn, "FAKE BANK", "FAKE CARD TYPE")
        insert_statement(
            conn,
            card_id,
            date(2026, 3, 1),
            date(2026, 3, 31),
            [
                _txn(1, "FIRST INSERTED", month=3),
                _txn(1, "SECOND INSERTED", month=3),
                _txn(1, "THIRD INSERTED", month=3),
            ],
        )

        rows = get_transactions(conn, start_date=date(2026, 3, 1), end_date=date(2026, 3, 1))

        # Same txn_date for all three -> ordering falls through to id DESC,
        # i.e. reverse insertion order.
        assert [row["description"] for row in rows] == [
            "THIRD INSERTED",
            "SECOND INSERTED",
            "FIRST INSERTED",
        ]
    finally:
        conn.close()


def test_statement_month_filter_narrows_to_matching_statement(db_path):
    conn = get_connection()
    try:
        card_id = create_card(conn, "FAKE BANK", "FAKE CARD TYPE")
        insert_statement(conn, card_id, date(2026, 1, 1), date(2026, 1, 31), [_txn(5, "JAN TXN")])
        insert_statement(
            conn, card_id, date(2026, 2, 1), date(2026, 2, 28), [_txn(5, "FEB TXN", month=2)]
        )

        rows = get_transactions(conn, statement_month="February-2026")

        assert _descriptions(rows) == {"FEB TXN"}
    finally:
        conn.close()


def test_bank_filter_narrows_to_matching_card(two_cards):
    conn = get_connection()
    try:
        rows = get_transactions(conn, bank="FAKE BANK A")
        assert _descriptions(rows) == {"CARD A TXN 1", "CARD A TXN 2", "CARD A TXN 3"}
    finally:
        conn.close()


def test_card_type_filter_narrows_to_matching_card(db_path):
    conn = get_connection()
    try:
        card_diners = create_card(conn, "FAKE BANK", "Diners")
        card_signature = create_card(conn, "FAKE BANK", "Signature")
        insert_statement(
            conn, card_diners, date(2026, 1, 1), date(2026, 1, 31), [_txn(5, "DINERS TXN")]
        )
        insert_statement(
            conn, card_signature, date(2026, 1, 1), date(2026, 1, 31), [_txn(5, "SIGNATURE TXN")]
        )

        rows = get_transactions(conn, card_type="Diners")

        assert _descriptions(rows) == {"DINERS TXN"}
    finally:
        conn.close()


def test_statement_month_composes_with_card_id_and_date_range(db_path):
    conn = get_connection()
    try:
        card_id = create_card(conn, "FAKE BANK", "FAKE CARD TYPE")
        other_card_id = create_card(conn, "FAKE BANK B", "FAKE CARD TYPE")

        insert_statement(
            conn,
            card_id,
            date(2026, 1, 1),
            date(2026, 1, 31),
            [_txn(5, "TARGET"), _txn(20, "OUT OF RANGE")],
        )
        insert_statement(
            conn, other_card_id, date(2026, 1, 1), date(2026, 1, 31), [_txn(5, "OTHER CARD")]
        )

        rows = get_transactions(
            conn,
            card_id=card_id,
            statement_month="January-2026",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 10),
        )

        assert _descriptions(rows) == {"TARGET"}
    finally:
        conn.close()


def test_list_statement_months_orders_by_period_end_desc_across_year_boundary(db_path):
    conn = get_connection()
    try:
        card_id = create_card(conn, "FAKE BANK", "FAKE CARD TYPE")
        insert_statement(
            conn, card_id, date(2025, 11, 17), date(2025, 12, 16), [_txn(1, "DEC TXN", month=12)]
        )
        insert_statement(
            conn, card_id, date(2025, 12, 17), date(2026, 1, 16), [_txn(1, "JAN TXN")]
        )

        # Alphabetically "December-2025" sorts before "January-2026" (D < J),
        # but chronologically January-2026 is the more recent statement --
        # this is exactly the case a naive alphabetical sort would get wrong.
        months = list_statement_months(conn)

        assert months == ["January-2026", "December-2025"]
    finally:
        conn.close()


def test_list_card_types_excludes_cards_without_statements(db_path):
    conn = get_connection()
    try:
        card_with_statement = create_card(conn, "FAKE BANK A", "FAKE CARD TYPE A")
        create_card(conn, "FAKE BANK B", "FAKE CARD TYPE B")  # no statement imported
        insert_statement(
            conn, card_with_statement, date(2026, 1, 1), date(2026, 1, 31), [_txn(5, "TXN")]
        )

        pairs = list_card_types(conn)

        assert pairs == [{"bank": "FAKE BANK A", "card_type": "FAKE CARD TYPE A"}]
    finally:
        conn.close()


def test_list_card_types_alphabetical_ordering(db_path):
    conn = get_connection()
    try:
        card_z = create_card(conn, "ZZZ BANK", "FAKE CARD TYPE")
        card_a = create_card(conn, "AAA BANK", "FAKE CARD TYPE")
        insert_statement(conn, card_z, date(2026, 1, 1), date(2026, 1, 31), [_txn(5, "TXN 1")])
        insert_statement(
            conn, card_a, date(2026, 2, 1), date(2026, 2, 28), [_txn(5, "TXN 2", month=2)]
        )

        pairs = list_card_types(conn)

        assert pairs == [
            {"bank": "AAA BANK", "card_type": "FAKE CARD TYPE"},
            {"bank": "ZZZ BANK", "card_type": "FAKE CARD TYPE"},
        ]
    finally:
        conn.close()
