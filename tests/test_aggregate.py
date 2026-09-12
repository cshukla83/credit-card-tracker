"""GET /transactions/aggregate and its two halves (Session 65).

All bank names, merchants, and amounts below are fabricated for testing.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from main import app
from storage import aggregate as agg
from storage.aggregate import PeriodError, aggregate_spend, resolve_period
from storage.cards import create_card
from storage.categories import assign_categories
from storage.db import get_connection, init_db
from storage.writes import insert_statement

TODAY = date(2026, 5, 15)


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setenv("DB_PATH", str(path))
    init_db()
    return str(path)


@pytest.fixture
def client(db_path, monkeypatch):
    monkeypatch.setattr(agg, "_today", lambda: TODAY)
    return TestClient(app)


def _txn(d, description, amount, txn_type="debit", is_payment=False):
    return {
        "txn_date": d,
        "description": description,
        "amount": amount,
        "txn_type": txn_type,
        "reward_points": None,
        "is_payment": is_payment,
    }


def _seed_card(conn, bank, card_type, rows, period=(date(2026, 1, 1), date(2026, 12, 31))):
    card_id = create_card(conn, bank, card_type)
    insert_statement(conn, card_id, period[0], period[1], rows)
    ids = [r["id"] for r in conn.execute(
        "SELECT t.id FROM transactions t JOIN statements s ON t.statement_id = s.id "
        "WHERE s.card_id = ? ORDER BY t.id", (card_id,)
    )]
    return card_id, ids


def _label(conn, txn_id, category=None, subcategory=None, merchant=None):
    assign_categories(conn, [(txn_id, category, subcategory, merchant, None)])


# --- resolve_period: relative windows --------------------------------------------


@pytest.mark.parametrize(
    "granularity, count, expected_start",
    [
        ("week", 1, date(2026, 5, 8)),
        ("week", 2, date(2026, 5, 1)),  # last 14 days
        ("month", 1, date(2026, 4, 15)),
        ("month", 3, date(2026, 2, 15)),  # calendar months back, not complete months
        ("quarter", 1, date(2026, 2, 15)),
        ("quarter", 2, date(2025, 11, 15)),  # crosses a year boundary
        ("year", 1, date(2025, 5, 15)),
    ],
)
def test_relative_windows_end_today_and_start_count_units_back(granularity, count, expected_start):
    assert resolve_period(granularity, "relative", count=count, today=TODAY) == (expected_start, TODAY)


def test_relative_month_clamps_day_to_target_month_length():
    # 31 Mar back one month -> Feb has no 31st; clamp to its last day.
    assert resolve_period("month", "relative", count=1, today=date(2026, 3, 31)) == (
        date(2026, 2, 28), date(2026, 3, 31),
    )
    assert resolve_period("year", "relative", count=1, today=date(2028, 2, 29)) == (
        date(2027, 2, 28), date(2028, 2, 29),
    )


# --- resolve_period: absolute periods and their edges -------------------------------


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        ({"month": "2026-02"}, (date(2026, 2, 1), date(2026, 2, 28))),
        ({"month": "2028-02"}, (date(2028, 2, 1), date(2028, 2, 29))),  # leap year
        ({"month": "2026-12"}, (date(2026, 12, 1), date(2026, 12, 31))),
    ],
)
def test_absolute_month_edges(kwargs, expected):
    assert resolve_period("month", "absolute", today=TODAY, **kwargs) == expected


@pytest.mark.parametrize(
    "quarter, expected",
    [
        ("2026-Q1", (date(2026, 1, 1), date(2026, 3, 31))),
        ("2026-Q2", (date(2026, 4, 1), date(2026, 6, 30))),
        ("2026-Q3", (date(2026, 7, 1), date(2026, 9, 30))),
        ("2026-Q4", (date(2026, 10, 1), date(2026, 12, 31))),
    ],
)
def test_absolute_quarter_edges(quarter, expected):
    assert resolve_period("quarter", "absolute", quarter=quarter, today=TODAY) == expected


def test_absolute_year_and_custom():
    assert resolve_period("year", "absolute", year="2025", today=TODAY) == (
        date(2025, 1, 1), date(2025, 12, 31),
    )
    assert resolve_period("custom", start="2026-01-10", end="2026-01-20") == (
        date(2026, 1, 10), date(2026, 1, 20),
    )
    assert resolve_period("custom", start="2026-01-10", end="2026-01-10")[0] == date(2026, 1, 10)


# --- resolve_period: rejections --------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs, fragment",
    [
        ({}, "granularity must be"),
        ({"granularity": "decade"}, "granularity must be"),
        ({"granularity": "month"}, "requires mode"),
        ({"granularity": "month", "mode": "sideways"}, "requires mode"),
        ({"granularity": "month", "mode": "relative"}, "requires count"),
        ({"granularity": "month", "mode": "relative", "count": 0}, "positive"),
        ({"granularity": "month", "mode": "relative", "count": -2}, "positive"),
        ({"granularity": "week", "mode": "absolute"}, "relative only"),
        ({"granularity": "month", "mode": "absolute"}, "month=YYYY-MM"),
        ({"granularity": "month", "mode": "absolute", "month": "2026-13"}, "month=YYYY-MM"),
        ({"granularity": "month", "mode": "absolute", "month": "Feb-2026"}, "month=YYYY-MM"),
        ({"granularity": "quarter", "mode": "absolute", "quarter": "2026-Q5"}, "quarter=YYYY-Qn"),
        ({"granularity": "quarter", "mode": "absolute"}, "quarter=YYYY-Qn"),
        ({"granularity": "year", "mode": "absolute", "year": "26"}, "year=YYYY"),
        ({"granularity": "custom"}, "requires start and end"),
        ({"granularity": "custom", "start": "2026-01-01"}, "requires start and end"),
        ({"granularity": "custom", "start": "2026-02-01", "end": "2026-01-01"}, "after end"),
        ({"granularity": "custom", "start": "01/01/2026", "end": "2026-01-31"}, "YYYY-MM-DD"),
        ({"granularity": "custom", "start": "2026-01-01", "end": "2026-01-31", "mode": "absolute"},
         "not applicable"),
    ],
)
def test_resolve_period_rejections(kwargs, fragment):
    granularity = kwargs.pop("granularity", None)
    with pytest.raises(PeriodError) as exc_info:
        resolve_period(granularity, today=TODAY, **kwargs)
    assert fragment in str(exc_info.value)


# --- aggregate_spend -------------------------------------------------------------------


@pytest.fixture
def ledger(db_path):
    """One card; a year of fabricated rows spanning categories, refunds, payments."""
    conn = get_connection()
    try:
        card_id, ids = _seed_card(conn, "FAKE BANK A", "FAKE TYPE", [
            _txn(date(2026, 4, 20), "FOOD ONE", 100.0),            # 0 Food/Cafe
            _txn(date(2026, 4, 22), "FOOD TWO", 50.0),             # 1 Food/(none)
            _txn(date(2026, 4, 25), "FOOD REFUND", 30.0, "credit"),  # 2 Food/Cafe refund
            _txn(date(2026, 5, 1), "TRAVEL ONE", 200.0),           # 3 Travel/Flights
            _txn(date(2026, 5, 2), "UNLABELLED", 10.0),            # 4 (none)/(none)
            _txn(date(2026, 5, 3), "SUB ONLY", 5.0),               # 5 (none)/Snacks
            _txn(date(2026, 5, 4), "BILL PAY", 500.0, "credit", is_payment=True),  # 6 excluded
            _txn(date(2026, 3, 31), "MARCH EDGE", 7.0),            # 7 Food, just before April
            _txn(date(2026, 5, 15), "TODAY", 3.0),                 # 8 Travel, on "today"
            _txn(date(2026, 5, 16), "TOMORROW", 1000.0),           # 9 Travel, after "today"
        ])
        _label(conn, ids[0], "Food", "Cafe")
        _label(conn, ids[1], "Food")
        _label(conn, ids[2], "Food", "Cafe")
        _label(conn, ids[3], "Travel", "Flights")
        _label(conn, ids[5], subcategory="Snacks")
        _label(conn, ids[7], "Food")
        _label(conn, ids[8], "Travel")
        _label(conn, ids[9], "Travel")
        # The payment row also carries labels (as the cascade would write):
        # they must not appear anywhere in the output.
        _label(conn, ids[6], "Credit Card Payment", "Credit Card Payment", "FAKE BANK A")
        return card_id, ids
    finally:
        conn.close()


def _by_cat(result):
    return {c["category"]: c for c in result["categories"]}


def test_aggregate_nets_refunds_groups_uncategorized_and_excludes_payments(ledger):
    conn = get_connection()
    try:
        result = aggregate_spend(conn, date(2026, 4, 1), date(2026, 5, 15))
        cats = _by_cat(result)
        assert list(cats) == ["Travel", "Food", "Uncategorized"]  # amount desc
        assert cats["Travel"]["amount"] == 203.0 and cats["Travel"]["transaction_count"] == 2
        # Food: 100 + 50 - 30 refund = 120 over 3 rows
        assert cats["Food"]["amount"] == 120.0 and cats["Food"]["transaction_count"] == 3
        food_subs = {s["subcategory"]: s for s in cats["Food"]["subcategories"]}
        assert food_subs["Cafe"]["amount"] == 70.0 and food_subs["Cafe"]["transaction_count"] == 2
        assert food_subs["Uncategorized"]["amount"] == 50.0
        assert [s["subcategory"] for s in cats["Food"]["subcategories"]] == ["Cafe", "Uncategorized"]
        # NULL category bucket: the unlabelled row and the subcategory-only row.
        unc = cats["Uncategorized"]
        assert unc["amount"] == 15.0 and unc["transaction_count"] == 2
        assert {s["subcategory"]: s["amount"] for s in unc["subcategories"]} == {
            "Uncategorized": 10.0, "Snacks": 5.0,
        }
        # The payment credit is nowhere: not a category, not in any count.
        assert "Credit Card Payment" not in cats
        assert result["total"] == 203.0 + 120.0 + 15.0
        assert result["period"] == {"start": "2026-04-01", "end": "2026-05-15"}
    finally:
        conn.close()


def test_aggregate_category_can_go_net_negative_and_is_not_clamped(db_path):
    conn = get_connection()
    try:
        _, ids = _seed_card(conn, "FAKE BANK A", "FAKE TYPE", [
            _txn(date(2026, 5, 1), "BUY", 20.0),
            _txn(date(2026, 5, 2), "BIG REFUND", 50.0, "credit"),
            _txn(date(2026, 5, 3), "OTHER", 5.0),
        ])
        _label(conn, ids[0], "Gadgets")
        _label(conn, ids[1], "Gadgets")
        _label(conn, ids[2], "Misc")
        result = aggregate_spend(conn, date(2026, 5, 1), date(2026, 5, 31))
        assert [(c["category"], c["amount"]) for c in result["categories"]] == [
            ("Misc", 5.0), ("Gadgets", -30.0),
        ]
        assert result["total"] == -25.0
    finally:
        conn.close()


def test_aggregate_period_edges_are_inclusive(ledger):
    conn = get_connection()
    try:
        # March 31 row is outside April..May; May 15 is inside; May 16 is outside.
        result = aggregate_spend(conn, date(2026, 4, 1), date(2026, 5, 15))
        assert result["total"] == 338.0
        result = aggregate_spend(conn, date(2026, 3, 31), date(2026, 5, 16))
        assert result["total"] == 338.0 + 7.0 + 1000.0
    finally:
        conn.close()


def test_aggregate_empty_period_is_zero_with_no_categories(ledger):
    conn = get_connection()
    try:
        result = aggregate_spend(conn, date(2020, 1, 1), date(2020, 12, 31))
        assert result == {
            "period": {"start": "2020-01-01", "end": "2020-12-31"},
            "total": 0.0,
            "categories": [],
        }
    finally:
        conn.close()


def test_aggregate_filters_narrow_like_transactions(db_path):
    conn = get_connection()
    try:
        card_a, ids_a = _seed_card(conn, "FAKE BANK A", "TYPE ONE", [_txn(date(2026, 5, 1), "A", 10.0)])
        card_b, ids_b = _seed_card(conn, "FAKE BANK B", "TYPE ONE", [_txn(date(2026, 5, 1), "B", 20.0)])
        card_c, ids_c = _seed_card(conn, "FAKE BANK B", "TYPE TWO", [_txn(date(2026, 5, 1), "C", 40.0)])
        may = (date(2026, 5, 1), date(2026, 5, 31))
        assert aggregate_spend(conn, *may)["total"] == 70.0
        assert aggregate_spend(conn, *may, bank="FAKE BANK B")["total"] == 60.0
        assert aggregate_spend(conn, *may, card_id=card_c)["total"] == 40.0
        assert aggregate_spend(conn, *may, card_type="TYPE ONE")["total"] == 30.0
        assert aggregate_spend(conn, *may, bank="FAKE BANK B", card_type="TYPE ONE")["total"] == 20.0
        assert aggregate_spend(conn, *may, bank="NO SUCH BANK")["total"] == 0.0
    finally:
        conn.close()


# --- endpoint --------------------------------------------------------------------------


def _get(client, **params):
    return client.get("/transactions/aggregate", params=params)


@pytest.mark.parametrize(
    "params, expected_period",
    [
        ({"granularity": "week", "mode": "relative", "count": 2}, ("2026-05-01", "2026-05-15")),
        ({"granularity": "month", "mode": "relative", "count": 1}, ("2026-04-15", "2026-05-15")),
        ({"granularity": "month", "mode": "absolute", "month": "2026-04"}, ("2026-04-01", "2026-04-30")),
        ({"granularity": "quarter", "mode": "relative", "count": 1}, ("2026-02-15", "2026-05-15")),
        ({"granularity": "quarter", "mode": "absolute", "quarter": "2026-Q2"}, ("2026-04-01", "2026-06-30")),
        ({"granularity": "year", "mode": "relative", "count": 1}, ("2025-05-15", "2026-05-15")),
        ({"granularity": "year", "mode": "absolute", "year": "2026"}, ("2026-01-01", "2026-12-31")),
        ({"granularity": "custom", "start": "2026-04-01", "end": "2026-05-15"}, ("2026-04-01", "2026-05-15")),
    ],
)
def test_endpoint_each_granularity_mode_echoes_resolved_period(client, ledger, params, expected_period):
    response = _get(client, **params)
    assert response.status_code == 200
    body = response.json()
    assert body["period"] == {"start": expected_period[0], "end": expected_period[1]}
    assert set(body.keys()) == {"period", "total", "categories"}
    for c in body["categories"]:
        assert set(c.keys()) == {"category", "amount", "transaction_count", "subcategories"}
        for s in c["subcategories"]:
            assert set(s.keys()) == {"subcategory", "amount", "transaction_count"}


def test_endpoint_relative_month_matches_direct_aggregation(client, ledger):
    body = _get(client, granularity="month", mode="relative", count=1).json()
    # 15 Apr .. 15 May: Food rows (20, 22, 25 Apr), Travel (1 May, 15 May),
    # uncategorized (2, 3 May); 31 Mar and 16 May are out; payment excluded.
    assert body["total"] == 338.0
    assert [c["category"] for c in body["categories"]] == ["Travel", "Food", "Uncategorized"]


def test_endpoint_absolute_month_boundaries(client, ledger):
    april = _get(client, granularity="month", mode="absolute", month="2026-04").json()
    assert april["total"] == 120.0  # Food only, refund netted; March 31 excluded
    march = _get(client, granularity="month", mode="absolute", month="2026-03").json()
    assert march["total"] == 7.0
    q2 = _get(client, granularity="quarter", mode="absolute", quarter="2026-Q2").json()
    assert q2["total"] == 120.0 + 203.0 + 15.0 + 1000.0  # includes 16 May, excludes payment


def test_endpoint_week_absolute_is_422(client, ledger):
    response = _get(client, granularity="week", mode="absolute")
    assert response.status_code == 422
    assert "relative only" in response.json()["detail"]


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"granularity": "month"},
        {"granularity": "month", "mode": "relative"},
        {"granularity": "month", "mode": "relative", "count": 0},
        {"granularity": "month", "mode": "relative", "count": -1},
        {"granularity": "month", "mode": "absolute"},
        {"granularity": "quarter", "mode": "absolute", "quarter": "2026-Q9"},
        {"granularity": "custom", "start": "2026-01-01"},
        {"granularity": "custom", "start": "2026-02-01", "end": "2026-01-01"},
        {"granularity": "custom", "start": "2026-01-01", "end": "2026-01-31", "mode": "relative"},
        {"granularity": "month", "mode": "relative", "count": "three"},
    ],
)
def test_endpoint_invalid_period_specs_are_422(client, ledger, params):
    response = _get(client, **params)
    assert response.status_code == 422
    assert response.json()["detail"]


def test_endpoint_filters_and_unknown_values(client, ledger):
    card_id, _ = ledger
    body = _get(client, granularity="year", mode="absolute", year="2026", card_id=card_id).json()
    assert body["total"] > 0
    body = _get(client, granularity="year", mode="absolute", year="2026", bank="NO SUCH BANK").json()
    assert body == {"period": {"start": "2026-01-01", "end": "2026-12-31"}, "total": 0.0, "categories": []}
