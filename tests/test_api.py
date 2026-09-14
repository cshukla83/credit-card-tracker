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
        "category",
        "subcategory",
        "merchant",
        "is_payment",
        "card_id",
        "bank",
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


def test_cards_all_true_includes_cards_without_statements(client, db_path):
    # Session 101: the upload screen's card picker needs every card, a
    # freshly created one included; the default stays statements-only.
    conn = get_connection()
    try:
        with_statement = create_card(conn, "FAKE BANK A", "FAKE CARD TYPE", "Primary")
        without_statement = create_card(conn, "FAKE BANK B", "FAKE CARD TYPE")
        insert_statement(conn, with_statement, date(2026, 1, 1), date(2026, 1, 31), [_txn(5, "X")])
    finally:
        conn.close()

    everything = client.get("/cards", params={"all": "true"})
    assert everything.status_code == 200
    assert [card["id"] for card in everything.json()] == [with_statement, without_statement]
    assert everything.json()[0]["nickname"] == "Primary"

    assert [card["id"] for card in client.get("/cards").json()] == [with_statement]
    assert [card["id"] for card in client.get("/cards", params={"all": "false"}).json()] == [with_statement]


def test_cards_all_true_ignores_filters(client, db_path):
    conn = get_connection()
    try:
        a = create_card(conn, "FAKE BANK A", "FAKE CARD TYPE")
        b = create_card(conn, "FAKE BANK B", "FAKE CARD TYPE")
    finally:
        conn.close()

    response = client.get("/cards", params={"all": "true", "bank": "FAKE BANK A"})
    assert [card["id"] for card in response.json()] == [a, b]


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


# --- categorization endpoints ---------------------------------------------


def _ids(client):
    return sorted(t["id"] for t in client.get("/transactions").json())


def test_suggestion_cold_start_is_200_with_none(client, two_cards):
    target = _ids(client)[0]
    response = client.get(f"/transactions/{target}/suggestion")
    assert response.status_code == 200
    # Session 55 shape: three parts. Category unset -> subcategory is null;
    # merchant is never null -- cold start falls back to the description.
    assert response.json() == {
        "category": {"value": None, "confidence": 0.0, "match_type": "none"},
        "subcategory": None,
        "merchant": {"value": "CARD A TXN 1", "confidence": None, "match_type": "from_description"},
    }


def test_suggestion_unknown_transaction_is_404(client, two_cards):
    assert client.get("/transactions/9999/suggestion").status_code == 404


def _pairs(ids, category):
    """Uniform assignment body: N pairs with the same category."""
    return {"assignments": [{"transaction_id": i, "category": category} for i in ids]}


def test_assign_then_suggest_round_trip(client, two_cards):
    # The fixture's five descriptions are all distinct, so an exact match
    # needs one seeded via the API; the rest exercise the fuzzy tier.
    ids = _ids(client)
    target, other = ids[0], ids[1]
    response = client.post("/transactions/category", json=_pairs([other], "Food"))
    assert response.status_code == 200
    assert response.json() == {"updated": 1}

    body = client.get(f"/transactions/{target}/suggestion").json()
    assert body["category"]["value"] == "Food"
    assert body["category"]["match_type"] == "fuzzy"
    assert 0.0 <= body["category"]["confidence"] <= 1.0
    assert body["subcategory"] is None  # target has no category yet
    # The categorized row itself: no exact description peer with a
    # subcategory, so the fallback is its own category.
    other_body = client.get(f"/transactions/{other}/suggestion").json()
    assert other_body["subcategory"] == {
        "value": "Food",
        "confidence": 1.0,
        "match_type": "same_as_category",
    }

    # And the write is visible on the listing endpoint.
    listed = {t["id"]: t["category"] for t in client.get("/transactions").json()}
    assert listed[other] == "Food"
    assert listed[target] is None


def test_assign_bulk_overwrites_including_already_categorized(client, two_cards):
    ids = _ids(client)
    client.post("/transactions/category", json=_pairs([ids[0]], "Food"))
    response = client.post("/transactions/category", json=_pairs(ids[:3], "Travel"))
    assert response.status_code == 200
    assert response.json()["updated"] == 3
    listed = {t["id"]: t["category"] for t in client.get("/transactions").json()}
    assert [listed[i] for i in ids] == ["Travel", "Travel", "Travel", None, None]


def test_assign_mixed_categories_in_one_request(client, two_cards):
    ids = _ids(client)
    response = client.post(
        "/transactions/category",
        json={
            "assignments": [
                {"transaction_id": ids[0], "category": "Food"},
                {"transaction_id": ids[1], "category": "Travel"},
                {"transaction_id": ids[2], "category": "Food"},
            ]
        },
    )
    assert response.status_code == 200
    assert response.json() == {"updated": 3}
    listed = {t["id"]: t["category"] for t in client.get("/transactions").json()}
    assert [listed[i] for i in ids] == ["Food", "Travel", "Food", None, None]


def test_assign_with_missing_id_is_404_and_writes_nothing(client, two_cards):
    ids = _ids(client)
    response = client.post("/transactions/category", json=_pairs([ids[0], 9999], "Food"))
    assert response.status_code == 404
    assert "9999" in response.json()["detail"]
    listed = {t["id"]: t["category"] for t in client.get("/transactions").json()}
    assert listed[ids[0]] is None


def test_assign_conflicting_pairs_for_one_id_is_422_and_writes_nothing(client, two_cards):
    ids = _ids(client)
    response = client.post(
        "/transactions/category",
        json={
            "assignments": [
                {"transaction_id": ids[0], "category": "Food"},
                {"transaction_id": ids[0], "category": "Travel"},
            ]
        },
    )
    assert response.status_code == 422
    listed = {t["id"]: t["category"] for t in client.get("/transactions").json()}
    assert listed[ids[0]] is None


def test_assign_strips_category_whitespace(client, two_cards):
    ids = _ids(client)
    response = client.post("/transactions/category", json=_pairs([ids[0]], "  Food  "))
    assert response.status_code == 200
    listed = {t["id"]: t["category"] for t in client.get("/transactions").json()}
    assert listed[ids[0]] == "Food"


@pytest.mark.parametrize(
    "sent, stored",
    [
        ("food and dining", "Food And Dining"),
        ("FOOD", "Food"),
        ("  travel  ", "Travel"),
        ("fOoD dElIvErY", "Food Delivery"),
        # str.title() is deliberately simple: it capitalises after any
        # non-letter. This oddity is the documented limitation, pinned so a
        # change to it is a decision rather than an accident.
        ("mcdonald's", "Mcdonald'S"),
    ],
)
def test_assign_normalizes_category_to_title_case(client, two_cards, sent, stored):
    ids = _ids(client)
    response = client.post("/transactions/category", json=_pairs([ids[0]], sent))
    assert response.status_code == 200
    listed = {t["id"]: t["category"] for t in client.get("/transactions").json()}
    assert listed[ids[0]] == stored


def test_case_variants_collapse_to_one_catalog_entry_and_one_suggestion(client, two_cards):
    # Without normalization "food" and "Food" would be two catalog entries
    # and, for the suggestion engine's Tier 1 majority count, two competing
    # categories with a 0.5 share each. With it they are one.
    ids = _ids(client)
    client.post(
        "/transactions/category",
        json={
            "assignments": [
                {"transaction_id": ids[1], "category": "food"},
                {"transaction_id": ids[2], "category": "Food"},
                {"transaction_id": ids[3], "category": "FOOD"},
            ]
        },
    )
    assert client.get("/categories").json() == ["Food"]
    # Only one "food" entry on a single row in a mixed request, too.
    response = client.post(
        "/transactions/category",
        json={
            "assignments": [
                {"transaction_id": ids[0], "category": "travel"},
                {"transaction_id": ids[0], "category": "Travel"},
            ]
        },
    )
    # Same id, same category after normalization: identical duplicates
    # collapse rather than being rejected as conflicting.
    assert response.status_code == 200
    assert response.json() == {"updated": 1}


@pytest.mark.parametrize(
    "payload",
    [
        {"assignments": []},
        {"assignments": [{"transaction_id": 1, "category": ""}]},
        {"assignments": [{"transaction_id": 1, "category": "   "}]},
        {"assignments": [{"transaction_id": 1}]},
        {"assignments": [{"category": "Food"}]},
        # The pre-Session-42 flat shape is gone, not tolerated alongside.
        {"transaction_ids": [1], "category": "Food"},
    ],
)
def test_assign_rejects_malformed_payloads(client, two_cards, payload):
    assert client.post("/transactions/category", json=payload).status_code == 422


# --- batch suggestions -----------------------------------------------------


def test_batch_suggestions_match_single_id_shape_and_order(client, two_cards):
    ids = _ids(client)
    client.post("/transactions/category", json=_pairs([ids[4]], "Food"))
    asked = [ids[2], ids[0], ids[4]]
    response = client.post("/transactions/suggestions", json={"transaction_ids": asked})
    assert response.status_code == 200
    body = response.json()["suggestions"]
    assert [s["transaction_id"] for s in body] == asked
    for entry in body:
        single = client.get(f"/transactions/{entry['transaction_id']}/suggestion").json()
        assert {k: v for k, v in entry.items() if k != "transaction_id"} == single
    # The categorized row itself gets no exact self-match; with nothing else
    # categorized it is a cold start.
    assert body[2]["category"]["match_type"] == "none"
    assert body[2]["subcategory"]["match_type"] == "same_as_category"


def test_batch_suggestions_run_categorized_query_once(client, two_cards, monkeypatch):
    import storage.categories as categories

    calls = []
    real = categories._fetch_labeled

    def counting(conn):
        calls.append(1)
        return real(conn)

    monkeypatch.setattr(categories, "_fetch_labeled", counting)
    ids = _ids(client)
    response = client.post("/transactions/suggestions", json={"transaction_ids": ids})
    assert response.status_code == 200
    assert len(response.json()["suggestions"]) == 5
    assert len(calls) == 1


def test_batch_suggestions_unknown_id_is_404(client, two_cards):
    ids = _ids(client)
    response = client.post(
        "/transactions/suggestions", json={"transaction_ids": [ids[0], 9999]}
    )
    assert response.status_code == 404
    assert "9999" in response.json()["detail"]


@pytest.mark.parametrize("payload", [{"transaction_ids": []}, {}, {"transaction_ids": "x"}])
def test_batch_suggestions_rejects_malformed_payloads(client, two_cards, payload):
    assert client.post("/transactions/suggestions", json=payload).status_code == 422


# --- categories catalog ----------------------------------------------------


def test_categories_catalog_is_empty_then_sorted_distinct(client, two_cards):
    assert client.get("/categories").json() == []
    ids = _ids(client)
    client.post(
        "/transactions/category",
        json={
            "assignments": [
                {"transaction_id": ids[0], "category": "Travel"},
                {"transaction_id": ids[1], "category": "Food"},
                {"transaction_id": ids[2], "category": "Food"},
            ]
        },
    )
    response = client.get("/categories")
    assert response.status_code == 200
    assert response.json() == ["Food", "Travel"]


# --- listing endpoints narrowed by the other filters -----------------------


@pytest.fixture
def two_cards_two_months(two_cards):
    """two_cards plus a February statement on Card A only (one txn, Feb 10)."""
    card_a, card_b = two_cards
    conn = get_connection()
    try:
        insert_statement(
            conn,
            card_a,
            date(2026, 2, 1),
            date(2026, 2, 28),
            [_txn(10, "CARD A FEB TXN", month=2)],
        )
    finally:
        conn.close()
    return card_a, card_b


def test_cards_narrow_by_statement_month(client, two_cards_two_months):
    card_a, card_b = two_cards_two_months
    assert [c["id"] for c in client.get("/cards").json()] == [card_a, card_b]
    assert [
        c["id"] for c in client.get("/cards", params={"statement_month": "February-2026"}).json()
    ] == [card_a]


def test_cards_narrow_by_bank_card_type_and_date_range(client, two_cards_two_months):
    card_a, card_b = two_cards_two_months
    assert [c["id"] for c in client.get("/cards", params={"bank": "FAKE BANK B"}).json()] == [
        card_b
    ]
    # Both cards share the card type.
    assert [
        c["id"] for c in client.get("/cards", params={"card_type": "FAKE CARD TYPE"}).json()
    ] == [card_a, card_b]
    # Only Card B has a transaction on/after Jan 20; only Card A has one in Feb.
    assert [c["id"] for c in client.get("/cards", params={"start": "2026-01-20"}).json()] == [
        card_a,
        card_b,
    ]
    assert [c["id"] for c in client.get("/cards", params={"start": "2026-01-21"}).json()] == [
        card_a
    ]
    assert [
        c["id"]
        for c in client.get("/cards", params={"start": "2026-01-16", "end": "2026-01-31"}).json()
    ] == [card_b]
    # A card appears once even when several of its transactions match.
    assert [
        c["id"] for c in client.get("/cards", params={"bank": "FAKE BANK A", "end": "2026-01-31"}).json()
    ] == [card_a]


def test_statement_months_narrow_by_card_bank_and_date_range(client, two_cards_two_months):
    card_a, card_b = two_cards_two_months
    assert client.get("/statement-months").json() == ["February-2026", "January-2026"]
    assert client.get("/statement-months", params={"card_id": card_b}).json() == ["January-2026"]
    assert client.get("/statement-months", params={"bank": "FAKE BANK A"}).json() == [
        "February-2026",
        "January-2026",
    ]
    assert client.get("/statement-months", params={"start": "2026-02-01"}).json() == [
        "February-2026"
    ]
    assert client.get(
        "/statement-months", params={"card_id": card_a, "end": "2026-01-31"}
    ).json() == ["January-2026"]
    assert client.get("/statement-months", params={"card_id": 9999}).json() == []


def test_card_types_narrow_by_card_month_bank_and_date_range(client, two_cards_two_months):
    card_a, _card_b = two_cards_two_months
    both = [
        {"bank": "FAKE BANK A", "card_type": "FAKE CARD TYPE"},
        {"bank": "FAKE BANK B", "card_type": "FAKE CARD TYPE"},
    ]
    only_a = both[:1]
    assert client.get("/card-types").json() == both
    assert client.get("/card-types", params={"card_id": card_a}).json() == only_a
    assert client.get("/card-types", params={"statement_month": "February-2026"}).json() == only_a
    assert client.get("/card-types", params={"bank": "FAKE BANK A"}).json() == only_a
    assert client.get("/card-types", params={"start": "2026-02-01"}).json() == only_a
    assert client.get("/card-types", params={"end": "2026-01-31"}).json() == both
    assert client.get("/card-types", params={"statement_month": "March-2026"}).json() == []


@pytest.mark.parametrize("path", ["/cards", "/statement-months", "/card-types"])
def test_listing_endpoints_validate_dates_like_transactions(client, two_cards, path):
    assert client.get(path, params={"start": "not-a-date"}).status_code == 400
    assert client.get(path, params={"start": "2026-02-01", "end": "2026-01-01"}).status_code == 400


def test_filter_sql_joins_only_what_the_filters_need():
    # The JOIN-only-when-needed discipline, asserted directly on the helper
    # rather than inferred from results.
    from storage.reads import filter_sql

    joins, where, params = filter_sql("transactions")
    assert (joins, where, params) == ("", "", [])

    joins, _, _ = filter_sql("transactions", card_id=1)
    assert "statements" in joins and "cards" not in joins

    joins, _, _ = filter_sql("transactions", bank="X")
    assert "JOIN statements" in joins and "JOIN cards" in joins

    joins, _, _ = filter_sql("statements", card_id=1)
    assert joins == ""

    joins, _, _ = filter_sql("statements", start_date="2026-01-01")
    assert "JOIN transactions" in joins and "cards" not in joins

    joins, _, _ = filter_sql("cards", always_join=("statements",))
    assert joins.strip() == "JOIN statements ON statements.card_id = cards.id"

    joins, _, _ = filter_sql("cards", end_date="2026-01-01", always_join=("statements",))
    assert joins.index("JOIN statements") < joins.index("JOIN transactions")


# --- clustering endpoint ----------------------------------------------------


@pytest.fixture
def similar_descriptions(db_path):
    """One card, six transactions: two families of three similar descriptions
    plus nothing else, so a 70% threshold yields exactly two clusters."""
    conn = get_connection()
    try:
        card = create_card(conn, "FAKE BANK", "FAKE CARD TYPE")
        insert_statement(
            conn,
            card,
            date(2026, 1, 1),
            date(2026, 1, 31),
            [
                _txn(1, "COFFEE SHOP 12"),
                _txn(2, "AIRLINE TICKETS 88"),
                _txn(3, "COFFEE SHOP 34"),
                _txn(4, "AIRLINE TICKETS 99"),
                _txn(5, "COFFEE SHOP 56"),
                _txn(6, "SOMETHING UNRELATED ZZZ"),
            ],
        )
        rows = conn.execute("SELECT id FROM transactions ORDER BY id").fetchall()
        return [r["id"] for r in rows]
    finally:
        conn.close()


def _cluster_ids(body):
    return [[m["transaction_id"] for m in c["members"]] for c in body["clusters"]]


def test_clusters_valid_request_groups_in_given_order(client, similar_descriptions):
    ids = similar_descriptions
    response = client.post("/transactions/clusters", json={"transaction_ids": ids, "threshold": 70})
    assert response.status_code == 200
    body = response.json()
    assert _cluster_ids(body) == [[ids[0], ids[2], ids[4]], [ids[1], ids[3]]]
    # Response shape: clusters only -- no leftover / ungrouped key of any kind.
    assert set(body.keys()) == {"clusters"}
    for cluster in body["clusters"]:
        assert set(cluster.keys()) == {"anchor_id", "members"}
        assert cluster["members"][0]["transaction_id"] == cluster["anchor_id"]
        assert cluster["members"][0]["similarity"] == 100.0
        for member in cluster["members"]:
            assert set(member.keys()) == {"transaction_id", "similarity"}
            assert 70.0 <= member["similarity"] <= 100.0


def test_clusters_report_known_pair_similarity(client, db_path):
    # "abcd" / "abce" is exactly 0.75 -> reported as 75.0 against the anchor.
    conn = get_connection()
    try:
        card = create_card(conn, "FAKE BANK", "FAKE CARD TYPE")
        insert_statement(
            conn, card, date(2026, 1, 1), date(2026, 1, 31), [_txn(1, "abcd"), _txn(2, "abce")]
        )
        a, b = [r["id"] for r in conn.execute("SELECT id FROM transactions ORDER BY id")]
    finally:
        conn.close()
    body = client.post(
        "/transactions/clusters", json={"transaction_ids": [a, b], "threshold": 75}
    ).json()
    assert body == {
        "clusters": [
            {
                "anchor_id": a,
                "members": [
                    {"transaction_id": a, "similarity": 100.0},
                    {"transaction_id": b, "similarity": 75.0},
                ],
            }
        ]
    }


def test_clusters_threshold_defaults_to_70(client, similar_descriptions):
    ids = similar_descriptions
    with_default = client.post("/transactions/clusters", json={"transaction_ids": ids}).json()
    explicit = client.post(
        "/transactions/clusters", json={"transaction_ids": ids, "threshold": 70}
    ).json()
    assert with_default == explicit


@pytest.mark.parametrize("threshold", [-1, 101, 250, "high"])
def test_clusters_out_of_range_threshold_is_422(client, similar_descriptions, threshold):
    response = client.post(
        "/transactions/clusters",
        json={"transaction_ids": similar_descriptions, "threshold": threshold},
    )
    assert response.status_code == 422


def test_clusters_empty_input_is_empty_result_not_error(client, similar_descriptions):
    response = client.post("/transactions/clusters", json={"transaction_ids": []})
    assert response.status_code == 200
    assert response.json() == {"clusters": []}


def test_clusters_all_singletons_is_empty_list(client, similar_descriptions):
    ids = similar_descriptions
    response = client.post(
        "/transactions/clusters", json={"transaction_ids": ids, "threshold": 100}
    )
    assert response.status_code == 200
    assert response.json() == {"clusters": []}


def test_clusters_unknown_id_is_404(client, similar_descriptions):
    response = client.post(
        "/transactions/clusters", json={"transaction_ids": [similar_descriptions[0], 9999]}
    )
    assert response.status_code == 404
    assert "9999" in response.json()["detail"]


def test_clusters_rejects_missing_ids_field(client, similar_descriptions):
    assert client.post("/transactions/clusters", json={"threshold": 70}).status_code == 422


# --- subcategory (Session 53) ----------------------------------------------


def _subcats(client):
    return {t["id"]: t["subcategory"] for t in client.get("/transactions").json()}


def _cats(client):
    return {t["id"]: t["category"] for t in client.get("/transactions").json()}


def test_assign_subcategory_only_writes_subcategory_and_normalizes(client, two_cards):
    ids = _ids(client)
    client.post("/transactions/category", json=_pairs([ids[0]], "Food"))
    response = client.post(
        "/transactions/category",
        json={"assignments": [{"transaction_id": ids[0], "subcategory": "  coffee shops "}]},
    )
    assert response.status_code == 200
    assert response.json() == {"updated": 1}
    assert _cats(client)[ids[0]] == "Food"
    assert _subcats(client)[ids[0]] == "Coffee Shops"


def test_suggestion_endpoints_carry_merchant_category_tier(client, two_cards):
    # Session 88: a (merchant, category) precedent from another row -- here
    # one whose description is nothing like the target's -- reaches both
    # suggestion endpoints unchanged, including the "precedents" count.
    ids = _ids(client)
    target, precedent = ids[0], ids[3]
    client.post(
        "/transactions/category",
        json={"assignments": [
            {"transaction_id": target, "category": "Food", "merchant": "corner shop"},
            {"transaction_id": precedent, "category": "food", "subcategory": "Snacks", "merchant": "Corner Shop"},
        ]},
    )
    expected = {"value": "Snacks", "confidence": 1.0, "match_type": "merchant_category", "precedents": 1}
    assert client.get(f"/transactions/{target}/suggestion").json()["subcategory"] == expected
    batch = client.post("/transactions/suggestions", json={"transaction_ids": [target]}).json()
    assert batch["suggestions"][0]["subcategory"] == expected


def test_assign_category_only_leaves_subcategory_alone(client, two_cards):
    ids = _ids(client)
    client.post(
        "/transactions/category",
        json={"assignments": [{"transaction_id": ids[0], "category": "Food", "subcategory": "Cafe"}]},
    )
    response = client.post("/transactions/category", json=_pairs([ids[0]], "Travel"))
    assert response.status_code == 200
    assert _cats(client)[ids[0]] == "Travel"
    assert _subcats(client)[ids[0]] == "Cafe"


def test_assign_both_fields_together(client, two_cards):
    ids = _ids(client)
    response = client.post(
        "/transactions/category",
        json={
            "assignments": [
                {"transaction_id": ids[0], "category": "food", "subcategory": "cafe"},
                {"transaction_id": ids[1], "category": "travel", "subcategory": "flights"},
            ]
        },
    )
    assert response.status_code == 200
    assert response.json() == {"updated": 2}
    assert [_cats(client)[i] for i in ids[:2]] == ["Food", "Travel"]
    assert [_subcats(client)[i] for i in ids[:2]] == ["Cafe", "Flights"]


@pytest.mark.parametrize(
    "assignment",
    [
        {"transaction_id": 1},
        {"transaction_id": 1, "subcategory": ""},
        {"transaction_id": 1, "subcategory": "   "},
        {"transaction_id": 1, "category": None, "subcategory": None},
    ],
)
def test_assign_pair_with_neither_field_is_422(client, two_cards, assignment):
    response = client.post("/transactions/category", json={"assignments": [assignment]})
    assert response.status_code == 422


def test_assign_conflicting_subcategories_for_one_id_is_422(client, two_cards):
    ids = _ids(client)
    response = client.post(
        "/transactions/category",
        json={
            "assignments": [
                {"transaction_id": ids[0], "subcategory": "Cafe"},
                {"transaction_id": ids[0], "subcategory": "Tea"},
            ]
        },
    )
    assert response.status_code == 422
    assert _subcats(client)[ids[0]] is None


def test_suggestion_endpoints_report_subcategory_exact_and_fallback(client, db_path):
    conn = get_connection()
    try:
        card = create_card(conn, "FAKE BANK", "FAKE CARD TYPE")
        insert_statement(
            conn, card, date(2026, 1, 1), date(2026, 1, 31),
            [_txn(1, "SHOP"), _txn(2, "SHOP"), _txn(3, "OTHER")],
        )
        target, peer, other = [r["id"] for r in conn.execute("SELECT id FROM transactions ORDER BY id")]
    finally:
        conn.close()
    client.post(
        "/transactions/category",
        json={
            "assignments": [
                {"transaction_id": target, "category": "Food"},
                {"transaction_id": peer, "category": "Food", "subcategory": "Cafe"},
            ]
        },
    )
    single = client.get(f"/transactions/{target}/suggestion").json()
    assert single["subcategory"] == {"value": "Cafe", "confidence": 1.0, "match_type": "exact"}
    assert single["category"]["match_type"] == "exact"

    batch = client.post(
        "/transactions/suggestions", json={"transaction_ids": [target, peer, other]}
    ).json()["suggestions"]
    by_id = {e["transaction_id"]: e for e in batch}
    assert by_id[target]["subcategory"] == single["subcategory"]
    assert by_id[peer]["subcategory"] == {
        "value": "Food",
        "confidence": 1.0,
        "match_type": "same_as_category",
    }
    assert by_id[other]["subcategory"] is None
    for entry in batch:
        assert set(entry.keys()) == {"transaction_id", "category", "subcategory", "merchant"}
        assert set(entry["category"].keys()) == {"value", "confidence", "match_type"}


def test_subcategories_catalog_unfiltered_and_filtered(client, two_cards):
    ids = _ids(client)
    assert client.get("/subcategories").json() == []
    client.post(
        "/transactions/category",
        json={
            "assignments": [
                {"transaction_id": ids[0], "category": "Food", "subcategory": "Tea"},
                {"transaction_id": ids[1], "category": "Food", "subcategory": "Cafe"},
                {"transaction_id": ids[2], "category": "Travel", "subcategory": "Flights"},
                {"transaction_id": ids[3], "category": "Food"},
            ]
        },
    )
    assert client.get("/subcategories").json() == ["Cafe", "Flights", "Tea"]
    assert client.get("/subcategories", params={"category": "Food"}).json() == ["Cafe", "Tea"]
    assert client.get("/subcategories", params={"category": "Travel"}).json() == ["Flights"]
    assert client.get("/subcategories", params={"category": "Nothing"}).json() == []


# --- merchant (Session 55) ---------------------------------------------------


def _field(client, name):
    return {t["id"]: t[name] for t in client.get("/transactions").json()}


@pytest.mark.parametrize(
    "assignment, expected",
    [
        ({"merchant": "corner shop"}, {"category": None, "subcategory": None, "merchant": "Corner Shop"}),
        ({"merchant": "corner shop", "category": "food"},
         {"category": "Food", "subcategory": None, "merchant": "Corner Shop"}),
        ({"merchant": "corner shop", "subcategory": "snacks"},
         {"category": None, "subcategory": "Snacks", "merchant": "Corner Shop"}),
        ({"merchant": "corner shop", "category": "food", "subcategory": "snacks"},
         {"category": "Food", "subcategory": "Snacks", "merchant": "Corner Shop"}),
    ],
)
def test_assign_merchant_field_combinations(client, two_cards, assignment, expected):
    ids = _ids(client)
    response = client.post(
        "/transactions/category", json={"assignments": [{"transaction_id": ids[0], **assignment}]}
    )
    assert response.status_code == 200
    assert response.json() == {"updated": 1}
    for name, value in expected.items():
        assert _field(client, name)[ids[0]] == value


def test_assign_conflicting_merchants_is_422(client, two_cards):
    ids = _ids(client)
    response = client.post(
        "/transactions/category",
        json={"assignments": [
            {"transaction_id": ids[0], "merchant": "A"},
            {"transaction_id": ids[0], "merchant": "B"},
        ]},
    )
    assert response.status_code == 422
    assert _field(client, "merchant")[ids[0]] is None


def test_suggestion_endpoints_report_merchant_tiers(client, db_path):
    conn = get_connection()
    try:
        card = create_card(conn, "FAKE BANK", "FAKE CARD TYPE")
        insert_statement(
            conn, card, date(2026, 1, 1), date(2026, 1, 31),
            [_txn(1, "SHOP"), _txn(2, "shop"), _txn(3, "SHOP 2")],
        )
        target, peer, near = [r["id"] for r in conn.execute("SELECT id FROM transactions ORDER BY id")]
    finally:
        conn.close()
    client.post("/transactions/category", json={"assignments": [{"transaction_id": peer, "merchant": "Alpha"}]})

    single = client.get(f"/transactions/{target}/suggestion").json()
    assert single["merchant"] == {"value": "Alpha", "confidence": 1.0, "match_type": "exact"}

    batch = client.post(
        "/transactions/suggestions", json={"transaction_ids": [target, peer, near]}
    ).json()["suggestions"]
    by_id = {e["transaction_id"]: e for e in batch}
    assert by_id[target]["merchant"] == single["merchant"]
    assert by_id[near]["merchant"]["match_type"] == "fuzzy"
    assert by_id[near]["merchant"]["value"] == "Alpha"
    # The only merchant-bearing row, excluded from its own candidates.
    assert by_id[peer]["merchant"] == {
        "value": "shop", "confidence": None, "match_type": "from_description",
    }
    for entry in batch:
        assert set(entry["merchant"].keys()) == {"value", "confidence", "match_type"}


def test_merchants_catalog_is_sorted_distinct_and_unscoped(client, two_cards):
    ids = _ids(client)
    assert client.get("/merchants").json() == []
    client.post(
        "/transactions/category",
        json={"assignments": [
            {"transaction_id": ids[0], "category": "Food", "merchant": "zeta"},
            {"transaction_id": ids[1], "category": "Travel", "merchant": "alpha"},
            {"transaction_id": ids[2], "merchant": "Alpha"},
        ]},
    )
    assert client.get("/merchants").json() == ["Alpha", "Zeta"]
    # No category scoping: the param is simply not part of this endpoint.
    assert client.get("/merchants", params={"category": "Food"}).json() == ["Alpha", "Zeta"]


# --- rows carry card_id and bank (Session 63) --------------------------------


def test_transactions_rows_carry_their_card_id_and_bank(client, two_cards):
    card_a, card_b = two_cards
    rows = client.get("/transactions").json()
    by_bank = {}
    for r in rows:
        by_bank.setdefault(r["bank"], set()).add(r["card_id"])
    assert by_bank == {"FAKE BANK A": {card_a}, "FAKE BANK B": {card_b}}
    # Consistent with the filters that use the same columns.
    only_b = client.get("/transactions", params={"card_id": card_b}).json()
    assert {(r["card_id"], r["bank"]) for r in only_b} == {(card_b, "FAKE BANK B")}
    only_a = client.get("/transactions", params={"bank": "FAKE BANK A"}).json()
    assert {(r["card_id"], r["bank"]) for r in only_a} == {(card_a, "FAKE BANK A")}
    # The row's own id is the transaction's, not a joined table's.
    assert sorted(r["id"] for r in rows) == _ids(client)


# --- filter_sql label filters (Session 74) ---------------------------------------


def test_filter_sql_label_filters_normalise_combine_and_map_uncategorized_to_null():
    from storage.reads import filter_sql

    joins, where, params = filter_sql("transactions", category=" food ")
    assert joins == "" and where == " WHERE transactions.category = ?" and params == ["Food"]
    # Uncategorized -> IS NULL, no parameter.
    joins, where, params = filter_sql("transactions", subcategory="uncategorized")
    assert where == " WHERE transactions.subcategory IS NULL" and params == []
    # All three together, with bank (cards join) and a date (no extra join).
    joins, where, params = filter_sql(
        "transactions", bank="B", start_date="2026-01-01", category="Food", subcategory="Cafe", merchant="Shop"
    )
    assert "JOIN statements" in joins and "JOIN cards" in joins and "transactions" not in joins.replace("transactions.", "")
    assert where.count("transactions.category = ?") == 1
    assert where.count("transactions.subcategory = ?") == 1
    assert where.count("transactions.merchant = ?") == 1
    assert params == ["B", "2026-01-01", "Food", "Cafe", "Shop"]
    # Empty / whitespace values are ignored.
    assert filter_sql("transactions", merchant="   ") == ("", "", [])
    # From another anchor the label filter walks to transactions.
    joins, where, _ = filter_sql("cards", merchant="Shop", always_join=("statements",))
    assert "JOIN transactions" in joins and "transactions.merchant = ?" in where


# --- label filters in the bidirectional mesh (Session 75) ---------------------


@pytest.fixture
def labelled_two_cards(two_cards_two_months):
    """two_cards_two_months with labels:

    Card A (FAKE BANK A): Jan 5 Food/Cafe/Bean Bar; Jan 10 Food/(none)/Corner
      Shop; Jan 15 (none); Feb 10 Travel/Flights/Sky Air.
    Card B (FAKE BANK B): Jan 8 Food/Cafe/(none); Jan 20 (none).
    """
    card_a, card_b = two_cards_two_months
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT t.id, t.txn_date, s.card_id FROM transactions t "
            "JOIN statements s ON t.statement_id = s.id ORDER BY t.id"
        ).fetchall()
        by = {(r["card_id"], r["txn_date"]): r["id"] for r in rows}
        assign_categories = __import__("storage.categories", fromlist=["assign_categories"]).assign_categories
        assign_categories(conn, [
            (by[(card_a, "2026-01-05")], "Food", "Cafe", "Bean Bar", None),
            (by[(card_a, "2026-01-10")], "Food", None, "Corner Shop", None),
            (by[(card_a, "2026-02-10")], "Travel", "Flights", "Sky Air", None),
            (by[(card_b, "2026-01-08")], "Food", "Cafe", None, None),
        ])
    finally:
        conn.close()
    return card_a, card_b


def _labels(client, **params):
    # (bank, date, ...) tuples sorted by date, so expectations read chronologically.
    return sorted(
        ((t["bank"], t["txn_date"], t["category"], t["subcategory"], t["merchant"])
         for t in client.get("/transactions", params=params).json()),
        key=lambda r: (r[1], r[0]),
    )


def test_transactions_label_filters_alone_combined_and_uncategorized(client, labelled_two_cards):
    card_a, card_b = labelled_two_cards
    assert len(client.get("/transactions").json()) == 6
    assert [r[1] for r in _labels(client, category="food")] == ["2026-01-05", "2026-01-08", "2026-01-10"]
    assert [r[1] for r in _labels(client, subcategory="Cafe")] == ["2026-01-05", "2026-01-08"]
    assert [r[1] for r in _labels(client, merchant="bean bar")] == ["2026-01-05"]
    # Combined with each other.
    assert [r[1] for r in _labels(client, category="Food", subcategory="Cafe", merchant="Bean Bar")] == ["2026-01-05"]
    assert _labels(client, category="Food", subcategory="Flights") == []
    # Combined with existing filters.
    assert [r[1] for r in _labels(client, category="Food", bank="FAKE BANK B")] == ["2026-01-08"]
    assert [r[1] for r in _labels(client, category="Food", card_id=card_a)] == ["2026-01-05", "2026-01-10"]
    assert [r[1] for r in _labels(client, category="Food", card_type="FAKE CARD TYPE", start="2026-01-09")] == ["2026-01-10"]
    assert [r[1] for r in _labels(client, subcategory="Flights", statement_month="February-2026")] == ["2026-02-10"]
    # Uncategorized -> NULL at each label.
    assert [r[1] for r in _labels(client, category="Uncategorized")] == ["2026-01-15", "2026-01-20"]
    assert [r[1] for r in _labels(client, subcategory="uncategorized")] == ["2026-01-10", "2026-01-15", "2026-01-20"]
    assert [r[1] for r in _labels(client, merchant="Uncategorized")] == ["2026-01-08", "2026-01-15", "2026-01-20"]
    assert [r[1] for r in _labels(client, category="Food", subcategory="Uncategorized")] == ["2026-01-10"]
    # Unknown label -> empty, like an unknown bank.
    assert client.get("/transactions", params={"category": "Nothing"}).json() == []


def test_label_catalogs_narrow_by_the_mesh_but_not_by_each_other(client, labelled_two_cards):
    card_a, card_b = labelled_two_cards
    # Unfiltered, as before.
    assert client.get("/categories").json() == ["Food", "Travel"]
    assert client.get("/subcategories").json() == ["Cafe", "Flights"]
    assert client.get("/merchants").json() == ["Bean Bar", "Corner Shop", "Sky Air"]
    # Each mesh param alone.
    assert client.get("/categories", params={"bank": "FAKE BANK B"}).json() == ["Food"]
    assert client.get("/categories", params={"card_id": card_b}).json() == ["Food"]
    assert client.get("/categories", params={"statement_month": "February-2026"}).json() == ["Travel"]
    assert client.get("/categories", params={"end": "2026-01-31"}).json() == ["Food"]
    assert client.get("/categories", params={"card_type": "FAKE CARD TYPE"}).json() == ["Food", "Travel"]
    assert client.get("/merchants", params={"bank": "FAKE BANK A", "start": "2026-01-09"}).json() == ["Corner Shop", "Sky Air"]
    assert client.get("/subcategories", params={"card_id": card_b}).json() == ["Cafe"]
    # All four narrowing params at once.
    assert client.get(
        "/merchants",
        params={"bank": "FAKE BANK A", "card_id": card_a, "card_type": "FAKE CARD TYPE",
                "statement_month": "January-2026", "start": "2026-01-01", "end": "2026-01-31"},
    ).json() == ["Bean Bar", "Corner Shop"]
    # Unknown values -> empty list, consistent with the other pickers.
    assert client.get("/categories", params={"bank": "NO SUCH BANK"}).json() == []
    assert client.get("/subcategories", params={"card_id": 9999}).json() == []
    assert client.get("/merchants", params={"card_type": "NO SUCH TYPE"}).json() == []
    # /subcategories' pre-existing category= scope is unchanged with no mesh params...
    assert client.get("/subcategories", params={"category": "Food"}).json() == ["Cafe"]
    assert client.get("/subcategories", params={"category": "Travel"}).json() == ["Flights"]
    # ...and composes with the mesh.
    assert client.get("/subcategories", params={"category": "Food", "bank": "FAKE BANK B"}).json() == ["Cafe"]
    assert client.get("/subcategories", params={"category": "Travel", "bank": "FAKE BANK B"}).json() == []
    # The three do NOT narrow each other: the params are simply not accepted
    # (ignored as unknown query params), so the lists are unchanged.
    assert client.get("/categories", params={"subcategory": "Flights"}).json() == ["Food", "Travel"]
    assert client.get("/categories", params={"merchant": "Sky Air"}).json() == ["Food", "Travel"]
    assert client.get("/merchants", params={"category": "Travel"}).json() == ["Bean Bar", "Corner Shop", "Sky Air"]
    assert client.get("/merchants", params={"subcategory": "Cafe"}).json() == ["Bean Bar", "Corner Shop", "Sky Air"]
    assert client.get("/subcategories", params={"merchant": "Sky Air"}).json() == ["Cafe", "Flights"]


def test_pickers_narrow_by_label_filters(client, labelled_two_cards):
    card_a, card_b = labelled_two_cards
    ids = lambda rows: [c["id"] for c in rows]
    # /cards
    assert ids(client.get("/cards", params={"category": "Travel"}).json()) == [card_a]
    assert ids(client.get("/cards", params={"category": "food"}).json()) == [card_a, card_b]
    assert ids(client.get("/cards", params={"merchant": "Uncategorized"}).json()) == [card_a, card_b]
    assert ids(client.get("/cards", params={"subcategory": "Cafe", "merchant": "Bean Bar"}).json()) == [card_a]
    assert ids(client.get("/cards", params={"category": "Food", "statement_month": "February-2026"}).json()) == []
    # Uncategorized category: cards with at least one unlabelled transaction.
    assert ids(client.get("/cards", params={"category": "Uncategorized"}).json()) == [card_a, card_b]
    assert ids(client.get("/cards", params={"category": "Uncategorized", "start": "2026-01-16"}).json()) == [card_b]
    # /statement-months
    assert client.get("/statement-months", params={"category": "Travel"}).json() == ["February-2026"]
    assert client.get("/statement-months", params={"subcategory": "Cafe"}).json() == ["January-2026"]
    assert client.get("/statement-months", params={"merchant": "Sky Air", "card_id": card_a}).json() == ["February-2026"]
    assert client.get("/statement-months", params={"category": "Uncategorized"}).json() == ["January-2026"]
    assert client.get("/statement-months", params={"category": "Nothing"}).json() == []
    # /card-types
    both = [{"bank": "FAKE BANK A", "card_type": "FAKE CARD TYPE"}, {"bank": "FAKE BANK B", "card_type": "FAKE CARD TYPE"}]
    assert client.get("/card-types", params={"category": "Food"}).json() == both
    assert client.get("/card-types", params={"merchant": "Bean Bar"}).json() == both[:1]
    assert client.get("/card-types", params={"subcategory": "Cafe", "merchant": "Uncategorized"}).json() == both[1:]
    assert client.get("/card-types", params={"category": "Travel", "bank": "FAKE BANK B"}).json() == []


# --- review_status filter (Session 80) ------------------------------------------


def test_review_status_incomplete_and_complete(client, labelled_two_cards):
    # Only Jan 5 (Card A) has all three labels; Feb 10 has all three too.
    complete = _labels(client, review_status="complete")
    assert [r[1] for r in complete] == ["2026-01-05", "2026-02-10"]
    assert all(None not in r[2:] for r in complete)
    incomplete = _labels(client, review_status="incomplete")
    assert [r[1] for r in incomplete] == ["2026-01-08", "2026-01-10", "2026-01-15", "2026-01-20"]
    assert all(None in r[2:] for r in incomplete)
    # The two partition the set.
    assert len(complete) + len(incomplete) == len(client.get("/transactions").json())


def test_review_status_combines_with_other_filters(client, labelled_two_cards):
    card_a, card_b = labelled_two_cards
    # Food rows still missing something: Card A Jan 10 (no subcategory) and Card B Jan 8 (no merchant).
    assert [r[1] for r in _labels(client, category="Food", review_status="incomplete")] == ["2026-01-08", "2026-01-10"]
    assert [r[1] for r in _labels(client, category="Food", review_status="complete")] == ["2026-01-05"]
    assert [r[1] for r in _labels(client, bank="FAKE BANK B", review_status="incomplete")] == ["2026-01-08", "2026-01-20"]
    assert [r[1] for r in _labels(client, card_id=card_a, statement_month="February-2026", review_status="complete")] == ["2026-02-10"]
    assert _labels(client, bank="FAKE BANK B", review_status="complete") == []
    assert [r[1] for r in _labels(client, start="2026-01-09", end="2026-01-31", review_status="incomplete")] == ["2026-01-10", "2026-01-15", "2026-01-20"]


@pytest.mark.parametrize("value", ["done", "COMPLETE", "", "partial"])
def test_review_status_invalid_value_is_422(client, labelled_two_cards, value):
    # A closed value set, case-sensitive; an empty value counts as given-but-
    # invalid, consistent with the other closed-set param (dimensions).
    response = client.get("/transactions", params={"review_status": value})
    assert response.status_code == 422
    assert "review_status must be one of" in response.json()["detail"]


def test_review_status_flows_through_to_aggregate(client, labelled_two_cards):
    base = {"granularity": "year", "mode": "absolute", "year": "2026"}
    all_rows = client.get("/transactions/aggregate", params=base).json()
    complete = client.get("/transactions/aggregate", params={**base, "review_status": "complete"})
    incomplete = client.get("/transactions/aggregate", params={**base, "review_status": "incomplete"})
    assert complete.status_code == 200 and incomplete.status_code == 200
    assert round(complete.json()["total"] + incomplete.json()["total"], 2) == all_rows["total"]
    assert "Uncategorized" not in {c["category"] for c in complete.json()["categories"]}
    assert client.get("/transactions/aggregate", params={**base, "review_status": "nope"}).status_code == 422


def test_filter_sql_review_status_clauses():
    from storage.reads import ReviewStatusError, filter_sql

    _, where, params = filter_sql("transactions", review_status="incomplete")
    assert where == " WHERE (transactions.category IS NULL OR transactions.subcategory IS NULL OR transactions.merchant IS NULL)"
    assert params == []
    _, where, _ = filter_sql("transactions", review_status="complete")
    assert "IS NOT NULL AND" in where
    # From another anchor it walks to transactions like the label filters.
    joins, where, _ = filter_sql("cards", review_status="incomplete", always_join=("statements",))
    assert "JOIN transactions" in joins and "transactions.category IS NULL" in where
    with pytest.raises(ReviewStatusError):
        filter_sql("transactions", review_status="maybe")


# --- Session 87: suggestions are not gated on the row's category --------------


def test_batch_suggestions_serve_rows_that_already_have_a_category(client, db_path):
    # The Review & Assign frontend once asked the engine only for rows with
    # no category, so category-set rows missing a subcategory or merchant
    # showed nothing (Session 87). The API never had that restriction: a
    # categorized-but-incomplete row gets merchant and subcategory
    # suggestions like any other. Pinned here so the contract is explicit.
    conn = get_connection()
    try:
        card = create_card(conn, "FAKE BANK", "FAKE CARD TYPE")
        insert_statement(
            conn, card, date(2026, 1, 1), date(2026, 1, 31),
            [_txn(1, "SHOP ONE"), _txn(2, "SHOP ONE"), _txn(3, "SHOP TWO")],
        )
        target, peer, near = [r["id"] for r in conn.execute("SELECT id FROM transactions ORDER BY id")]
    finally:
        conn.close()
    client.post("/transactions/category", json={"assignments": [
        {"transaction_id": target, "category": "Food"},                       # category only
        {"transaction_id": peer, "category": "Food", "subcategory": "Cafe", "merchant": "Bean Bar"},
        {"transaction_id": near, "category": "Travel"},                       # category only
    ]})
    body = client.post("/transactions/suggestions", json={"transaction_ids": [target, near]}).json()
    by_id = {s["transaction_id"]: s for s in body["suggestions"]}
    # Exact description peer with a merchant and subcategory: both learned.
    assert by_id[target]["merchant"] == {"value": "Bean Bar", "confidence": 1.0, "match_type": "exact"}
    assert by_id[target]["subcategory"] == {"value": "Cafe", "confidence": 1.0, "match_type": "exact"}
    # Different description and category: merchant fuzzy (no floor), subcategory falls back.
    assert by_id[near]["merchant"]["match_type"] == "fuzzy"
    assert by_id[near]["merchant"]["value"] == "Bean Bar"
    assert 0.0 < by_id[near]["merchant"]["confidence"] < 1.0
    assert by_id[near]["subcategory"]["match_type"] == "same_as_category"
    # Category suggestions are still produced for both (the frontend ignores
    # them for rows that already have a category; the API does not).
    assert by_id[target]["category"]["match_type"] == "exact"
