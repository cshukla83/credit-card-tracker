from datetime import date

import pytest
from fastapi.testclient import TestClient

from main import app
from storage.cards import create_card
from storage.db import get_connection, init_db
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
def client(db_path):
    return TestClient(app)


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


def test_no_filters_returns_all_transactions(client, two_cards):
    response = client.get("/transactions")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 5
    assert set(body[0].keys()) == {
        "id",
        "statement_id",
        "txn_date",
        "description",
        "amount",
        "txn_type",
        "reward_points",
    }


def test_all_filters_narrow_to_expected_subset(client, two_cards):
    card_a, _card_b = two_cards

    response = client.get(
        "/transactions", params={"card_id": card_a, "start": "2026-01-08", "end": "2026-01-15"}
    )

    assert response.status_code == 200
    descriptions = {t["description"] for t in response.json()}
    assert descriptions == {"CARD A TXN 2", "CARD A TXN 3"}


@pytest.mark.parametrize("bad_start", ["not-a-date", "2026-13-01"])
def test_malformed_start_returns_400_naming_start(client, two_cards, bad_start):
    response = client.get("/transactions", params={"start": bad_start})

    assert response.status_code == 400
    assert "start" in response.json()["detail"]


def test_start_after_end_returns_400(client, two_cards):
    response = client.get("/transactions", params={"start": "2026-02-01", "end": "2026-01-01"})

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "start" in detail and "end" in detail


def test_empty_result_returns_200_and_empty_list(client, two_cards):
    response = client.get("/transactions", params={"start": "2030-01-01", "end": "2030-01-31"})

    assert response.status_code == 200
    assert response.json() == []


def test_unknown_card_id_returns_200_and_empty_list(client, two_cards):
    # Locks in the "no second lookup" decision: an id that doesn't exist in
    # cards behaves exactly like a card with no matching transactions.
    response = client.get("/transactions", params={"card_id": 999999})

    assert response.status_code == 200
    assert response.json() == []


def test_root_serves_html_page(client, db_path):
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'id="transactions-table"' in response.text


def test_cards_empty_db_returns_200_and_empty_list(client, db_path):
    response = client.get("/cards")

    assert response.status_code == 200
    assert response.json() == []


def test_cards_with_no_statements_returns_empty_list(client, db_path):
    conn = get_connection()
    try:
        create_card(conn, "FAKE BANK A", "FAKE CARD TYPE")
        create_card(conn, "FAKE BANK B", "FAKE CARD TYPE")
    finally:
        conn.close()

    response = client.get("/cards")

    assert response.status_code == 200
    assert response.json() == []


def test_cards_returns_only_cards_with_statements_ordered_by_id(client, db_path):
    conn = get_connection()
    try:
        card_with_statement = create_card(conn, "FAKE BANK A", "FAKE CARD TYPE")
        card_without_statement = create_card(conn, "FAKE BANK B", "FAKE CARD TYPE")
        insert_statement(
            conn,
            card_with_statement,
            date(2026, 1, 1),
            date(2026, 1, 31),
            [_txn(5, "CARD A TXN 1")],
        )
    finally:
        conn.close()

    response = client.get("/cards")

    assert response.status_code == 200
    body = response.json()
    assert [card["id"] for card in body] == [card_with_statement]
    assert card_without_statement not in [card["id"] for card in body]
    assert set(body[0].keys()) == {"id", "bank", "card_type", "nickname", "created_at"}


def test_cards_with_multiple_statements_appears_once(client, db_path):
    conn = get_connection()
    try:
        card_id = create_card(conn, "FAKE BANK A", "FAKE CARD TYPE")
        insert_statement(
            conn, card_id, date(2026, 1, 1), date(2026, 1, 31), [_txn(5, "CARD A TXN 1")]
        )
        insert_statement(
            conn, card_id, date(2026, 2, 1), date(2026, 2, 28), [_txn(5, "CARD A TXN 2", month=2)]
        )
    finally:
        conn.close()

    response = client.get("/cards")

    assert response.status_code == 200
    assert [card["id"] for card in response.json()] == [card_id]


def test_statement_months_returns_desc_period_end_order(client, db_path):
    conn = get_connection()
    try:
        card_id = create_card(conn, "FAKE BANK", "FAKE CARD TYPE")
        insert_statement(
            conn, card_id, date(2025, 12, 17), date(2026, 1, 16), [_txn(1, "JAN TXN")]
        )
        insert_statement(
            conn, card_id, date(2025, 11, 17), date(2025, 12, 16), [_txn(1, "DEC TXN", month=12)]
        )
    finally:
        conn.close()

    response = client.get("/statement-months")

    assert response.status_code == 200
    assert response.json() == ["January-2026", "December-2025"]


def test_statement_months_empty_db_returns_200_and_empty_list(client, db_path):
    response = client.get("/statement-months")

    assert response.status_code == 200
    assert response.json() == []


def test_card_types_returns_alphabetical_bank_card_type_pairs(client, db_path):
    conn = get_connection()
    try:
        card_z = create_card(conn, "ZZZ BANK", "FAKE CARD TYPE")
        card_a = create_card(conn, "AAA BANK", "FAKE CARD TYPE")
        insert_statement(conn, card_z, date(2026, 1, 1), date(2026, 1, 31), [_txn(5, "TXN 1")])
        insert_statement(
            conn, card_a, date(2026, 2, 1), date(2026, 2, 28), [_txn(5, "TXN 2", month=2)]
        )
    finally:
        conn.close()

    response = client.get("/card-types")

    assert response.status_code == 200
    assert response.json() == [
        {"bank": "AAA BANK", "card_type": "FAKE CARD TYPE"},
        {"bank": "ZZZ BANK", "card_type": "FAKE CARD TYPE"},
    ]


def test_card_types_empty_db_returns_200_and_empty_list(client, db_path):
    response = client.get("/card-types")

    assert response.status_code == 200
    assert response.json() == []


def test_transactions_statement_month_filter(client, two_cards):
    response = client.get("/transactions", params={"statement_month": "January-2026"})

    assert response.status_code == 200
    assert len(response.json()) == 5


def test_transactions_unknown_statement_month_returns_empty_list(client, two_cards):
    response = client.get("/transactions", params={"statement_month": "March-2099"})

    assert response.status_code == 200
    assert response.json() == []


def test_transactions_bank_filter(client, two_cards):
    response = client.get("/transactions", params={"bank": "FAKE BANK A"})

    assert response.status_code == 200
    descriptions = {t["description"] for t in response.json()}
    assert descriptions == {"CARD A TXN 1", "CARD A TXN 2", "CARD A TXN 3"}


def test_transactions_unknown_bank_returns_empty_list(client, two_cards):
    response = client.get("/transactions", params={"bank": "NOT A REAL BANK"})

    assert response.status_code == 200
    assert response.json() == []


def test_transactions_card_type_filter(client, two_cards):
    # Both fixture cards share "FAKE CARD TYPE", so this exercises the cards
    # JOIN without narrowing -- narrowing behavior is covered separately at
    # the storage layer (test_reads.py), where the fixture cards differ.
    response = client.get("/transactions", params={"card_type": "FAKE CARD TYPE"})

    assert response.status_code == 200
    assert len(response.json()) == 5


def test_transactions_unknown_card_type_returns_empty_list(client, two_cards):
    response = client.get("/transactions", params={"card_type": "NOT A REAL TYPE"})

    assert response.status_code == 200
    assert response.json() == []


def test_transactions_new_filters_compose_as_and(client, two_cards):
    card_a, _card_b = two_cards

    response = client.get(
        "/transactions",
        params={
            "card_id": card_a,
            "bank": "FAKE BANK A",
            "card_type": "FAKE CARD TYPE",
            "statement_month": "January-2026",
            "start": "2026-01-08",
            "end": "2026-01-15",
        },
    )

    assert response.status_code == 200
    descriptions = {t["description"] for t in response.json()}
    assert descriptions == {"CARD A TXN 2", "CARD A TXN 3"}
