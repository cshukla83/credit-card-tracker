"""GET /transactions?page=N -- the paged form behind the dashboard's
drill-down transaction list.

All banks, merchants, and amounts below are fabricated for testing.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from main import app
from storage.cards import create_card
from storage.db import get_connection, init_db
from storage.reads import TRANSACTIONS_PAGE_SIZE
from storage.writes import insert_statement


def _txn(d, description, amount, txn_type="debit"):
    return {
        "txn_date": d,
        "description": description,
        "amount": amount,
        "txn_type": txn_type,
        "reward_points": None,
    }


def _label(conn, description, category, subcategory, merchant, is_payment=0):
    conn.execute(
        "UPDATE transactions SET category = ?, subcategory = ?, merchant = ?, is_payment = ? "
        "WHERE description = ?",
        (category, subcategory, merchant, is_payment, description),
    )


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    init_db()
    return TestClient(app)


@pytest.fixture
def labelled(client):
    """One card. March 2026 holds seven labelled-or-not rows; one row each
    on the days either side of March, labelled like a March row, so a date
    bound that leaks shows up.

      SYN-1  Mar 1   debit  100  Food / Dining / Alpha Cafe
      SYN-2  Mar 10  debit   40  Food / Groceries / Beta Mart
      SYN-3  Mar 15  credit  15  Food / Dining / Alpha Cafe        (refund)
      SYN-4  Mar 20  debit   60  Travel / Taxi / Gamma Rides
      SYN-5  Mar 25  debit   25  Travel / Dining / Alpha Cafe
      SYN-6  Mar 28  credit 500  Credit Card Payment x2 / Synth Bank (payment)
      SYN-7  Mar 31  debit    7  (no labels)
      SYN-OUT-1 Feb 28, SYN-OUT-2 Apr 1: debit 9, Food / Dining / Alpha Cafe
    """
    conn = get_connection()
    try:
        card = create_card(conn, "SYNTH BANK", "SYNTH CARD")
        insert_statement(conn, card, date(2026, 2, 1), date(2026, 2, 28),
                         [_txn(date(2026, 2, 28), "SYN-OUT-1", 9)])
        insert_statement(conn, card, date(2026, 3, 1), date(2026, 3, 31), [
            _txn(date(2026, 3, 1), "SYN-1", 100),
            _txn(date(2026, 3, 10), "SYN-2", 40),
            _txn(date(2026, 3, 15), "SYN-3", 15, "credit"),
            _txn(date(2026, 3, 20), "SYN-4", 60),
            _txn(date(2026, 3, 25), "SYN-5", 25),
            _txn(date(2026, 3, 28), "SYN-6", 500, "credit"),
            _txn(date(2026, 3, 31), "SYN-7", 7),
        ])
        insert_statement(conn, card, date(2026, 4, 1), date(2026, 4, 30),
                         [_txn(date(2026, 4, 1), "SYN-OUT-2", 9)])
        for d in ("SYN-1", "SYN-3", "SYN-OUT-1", "SYN-OUT-2"):
            _label(conn, d, "Food", "Dining", "Alpha Cafe")
        _label(conn, "SYN-2", "Food", "Groceries", "Beta Mart")
        _label(conn, "SYN-4", "Travel", "Taxi", "Gamma Rides")
        _label(conn, "SYN-5", "Travel", "Dining", "Alpha Cafe")
        _label(conn, "SYN-6", "Credit Card Payment", "Credit Card Payment", "Synth Bank", is_payment=1)
        conn.commit()
    finally:
        conn.close()
    return card


MARCH = {"start": "2026-03-01", "end": "2026-03-31"}


def _page(client, **params):
    response = client.get("/transactions", params={"page": 1, **params})
    assert response.status_code == 200, response.text
    return response.json()


def _descs(body):
    return [t["description"] for t in body["transactions"]]


# --- shape and backward compatibility ----------------------------------------

def test_without_page_the_response_is_the_unchanged_bare_list(client, labelled):
    body = client.get("/transactions", params=MARCH).json()
    assert isinstance(body, list)
    assert len(body) == 7


def test_paged_response_shape(client, labelled):
    body = _page(client, **MARCH)
    assert set(body) == {"transactions", "total", "page", "page_size"}
    assert body["page"] == 1
    assert body["page_size"] == TRANSACTIONS_PAGE_SIZE == 25
    assert body["total"] == 7
    row = body["transactions"][0]
    # Same row shape as the unpaged list: the card is identifiable.
    assert {"txn_date", "amount", "txn_type", "category", "subcategory", "merchant",
            "card_id", "bank"} <= set(row)


def test_paged_rows_match_the_unpaged_list_in_order(client, labelled):
    unpaged = client.get("/transactions", params=MARCH).json()
    assert _page(client, **MARCH)["transactions"] == unpaged


# --- each new-to-the-list filter on its own ------------------------------------

def test_category_filter(client, labelled):
    body = _page(client, category="Food", **MARCH)
    assert sorted(_descs(body)) == ["SYN-1", "SYN-2", "SYN-3"]
    assert body["total"] == 3


def test_subcategory_filter(client, labelled):
    body = _page(client, subcategory="Dining", **MARCH)
    assert sorted(_descs(body)) == ["SYN-1", "SYN-3", "SYN-5"]
    assert body["total"] == 3


def test_merchant_filter(client, labelled):
    body = _page(client, merchant="Alpha Cafe", **MARCH)
    assert sorted(_descs(body)) == ["SYN-1", "SYN-3", "SYN-5"]


def test_label_filter_is_normalised_like_the_dashboard(client, labelled):
    assert sorted(_descs(_page(client, merchant="alpha cafe", **MARCH))) == ["SYN-1", "SYN-3", "SYN-5"]


def test_uncategorized_selects_unlabelled_rows(client, labelled):
    body = _page(client, category="Uncategorized", **MARCH)
    assert _descs(body) == ["SYN-7"]


def test_start_filter_alone(client, labelled):
    body = _page(client, start="2026-03-31")
    assert sorted(_descs(body)) == ["SYN-7", "SYN-OUT-2"]


def test_end_filter_alone(client, labelled):
    body = _page(client, end="2026-03-01")
    assert sorted(_descs(body)) == ["SYN-1", "SYN-OUT-1"]


# --- combined -----------------------------------------------------------------

def test_category_and_merchant_combined(client, labelled):
    # Alpha Cafe appears under Food and Travel; the pair narrows to Travel's.
    assert _descs(_page(client, category="Travel", merchant="Alpha Cafe", **MARCH)) == ["SYN-5"]


def test_all_three_labels_combined(client, labelled):
    body = _page(client, category="Food", subcategory="Dining", merchant="Alpha Cafe", **MARCH)
    assert sorted(_descs(body)) == ["SYN-1", "SYN-3"]
    assert body["total"] == 2


def test_labels_combined_with_card_and_bank(client, labelled):
    body = _page(client, category="Food", card_id=labelled, bank="SYNTH BANK", **MARCH)
    assert body["total"] == 3
    assert _page(client, category="Food", bank="OTHER BANK", **MARCH)["total"] == 0


def test_combination_with_no_match_is_empty_not_an_error(client, labelled):
    body = _page(client, category="Travel", merchant="Beta Mart", **MARCH)
    assert body == {"transactions": [], "total": 0, "page": 1, "page_size": 25}


# --- date bounds --------------------------------------------------------------

def test_date_bounds_are_inclusive_at_both_ends(client, labelled):
    body = _page(client, category="Food", subcategory="Dining", merchant="Alpha Cafe", **MARCH)
    # Mar 1 is on the start bound; Feb 28 and Apr 1 sit one day outside.
    assert "SYN-1" in _descs(body)
    assert "SYN-OUT-1" not in _descs(body) and "SYN-OUT-2" not in _descs(body)
    assert _descs(_page(client, start="2026-03-31", end="2026-03-31")) == ["SYN-7"]


def test_single_day_range_on_the_first_day(client, labelled):
    assert _descs(_page(client, start="2026-03-01", end="2026-03-01")) == ["SYN-1"]


# --- debits and credits alike -------------------------------------------------

def test_refunds_and_payments_are_listed(client, labelled):
    descs = _descs(_page(client, **MARCH))
    assert "SYN-3" in descs  # refund credit
    assert "SYN-6" in descs  # payment to the card
    payment = _page(client, merchant="Synth Bank", **MARCH)["transactions"]
    assert [(t["txn_type"], t["is_payment"]) for t in payment] == [("credit", 1)]


# --- pagination ---------------------------------------------------------------

@pytest.fixture
def sixty(client):
    """60 debits in January 2026, all Bulk / Bulk Sub / Bulk Shop, three per
    day on days 1-20 -- so ties on txn_date exercise the id tiebreak."""
    conn = get_connection()
    try:
        card = create_card(conn, "SYNTH BANK", "SYNTH CARD")
        txns = [_txn(date(2026, 1, 1 + i // 3), f"BULK-{i:02d}", 1 + i) for i in range(60)]
        insert_statement(conn, card, date(2026, 1, 1), date(2026, 1, 31), txns)
        conn.execute("UPDATE transactions SET category = 'Bulk', subcategory = 'Bulk Sub', merchant = 'Bulk Shop'")
        conn.commit()
    finally:
        conn.close()


JAN = {"start": "2026-01-01", "end": "2026-01-31", "category": "Bulk"}


def test_pages_split_at_25_with_the_true_total(client, sixty):
    sizes = []
    for n in (1, 2, 3):
        body = client.get("/transactions", params={**JAN, "page": n}).json()
        assert body["total"] == 60
        assert body["page"] == n
        sizes.append(len(body["transactions"]))
    assert sizes == [25, 25, 10]


def test_page_past_the_end_is_empty_with_the_total(client, sixty):
    body = client.get("/transactions", params={**JAN, "page": 4}).json()
    assert body["transactions"] == []
    assert body["total"] == 60


def test_pages_concatenate_to_the_unpaged_list_without_gaps_or_repeats(client, sixty):
    unpaged = client.get("/transactions", params=JAN).json()
    paged = []
    for n in (1, 2, 3):
        paged += client.get("/transactions", params={**JAN, "page": n}).json()["transactions"]
    assert [t["id"] for t in paged] == [t["id"] for t in unpaged]
    assert len({t["id"] for t in paged}) == 60


def test_page_boundary_rows(client, sixty):
    unpaged = client.get("/transactions", params=JAN).json()
    p1 = client.get("/transactions", params={**JAN, "page": 1}).json()["transactions"]
    p2 = client.get("/transactions", params={**JAN, "page": 2}).json()["transactions"]
    assert p1[-1]["id"] == unpaged[24]["id"]
    assert p2[0]["id"] == unpaged[25]["id"]


@pytest.mark.parametrize("bad", ["0", "-1", "abc", "1.5"])
def test_invalid_page_is_422(client, sixty, bad):
    assert client.get("/transactions", params={**JAN, "page": bad}).status_code == 422


def test_paged_form_keeps_the_existing_date_and_review_status_errors(client, sixty):
    assert client.get("/transactions", params={"start": "2026-13-01", "page": 1}).status_code == 400
    assert client.get("/transactions", params={"start": "2026-01-31", "end": "2026-01-01", "page": 1}).status_code == 400
    assert client.get("/transactions", params={"review_status": "nope", "page": 1}).status_code == 422
