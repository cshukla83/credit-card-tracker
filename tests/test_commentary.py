"""LLM commentary endpoint, cache, and payload narrowing (Session 68).

The Gemini call is mocked everywhere; nothing here touches the network.
All bank names, merchants, and amounts are fabricated.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from main import app
from storage import aggregate as agg
from storage import commentary as com
from storage.aggregate import resolve_period
from storage.cards import create_card
from storage.categories import assign_categories
from storage.commentary import (
    CommentaryNotConfiguredError,
    CommentaryUnavailableError,
    generate_commentary,
    get_cached,
    narrow_payload,
    query_signature,
    upsert_cached,
)
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
def with_key(monkeypatch):
    monkeypatch.setenv(com.API_KEY_ENV, "fake-test-key")


@pytest.fixture
def client(db_path, monkeypatch):
    monkeypatch.setattr(agg, "_today", lambda: TODAY)
    return TestClient(app)


@pytest.fixture
def seeded(db_path):
    conn = get_connection()
    try:
        card = create_card(conn, "FAKE BANK", "FAKE TYPE")
        insert_statement(conn, card, date(2026, 1, 1), date(2026, 12, 31), [
            {"txn_date": date(2026, 5, 1), "description": "FAKE SHOP ONE", "amount": 100.0,
             "txn_type": "debit", "reward_points": None},
            {"txn_date": date(2026, 5, 2), "description": "FAKE SHOP TWO", "amount": 40.0,
             "txn_type": "debit", "reward_points": None},
        ])
        ids = [r["id"] for r in conn.execute("SELECT id FROM transactions ORDER BY id")]
        assign_categories(conn, [(ids[0], "Food", "Cafe", "Shop One", None)])
        return card
    finally:
        conn.close()


def _fake_gemini(text="Most spending went on food this period."):
    calls = []

    def fake(api_key, payload):
        calls.append({"api_key": api_key, "payload": payload})
        return text

    fake.calls = calls
    return fake


def _failing_gemini(exc=RuntimeError("boom")):
    def fake(api_key, payload):
        raise exc

    return fake


# --- query_signature --------------------------------------------------------------


def test_signature_is_deterministic_and_normalises_absent_filters():
    a = query_signature(date(2026, 4, 1), date(2026, 4, 30))
    b = query_signature(date(2026, 4, 1), date(2026, 4, 30), bank=None, card_id=None, card_type=None)
    c = query_signature(date(2026, 4, 1), date(2026, 4, 30), bank="", card_type="   ")
    assert a == b == c
    assert query_signature(date(2026, 4, 1), date(2026, 4, 30), bank="X") != a
    assert query_signature(date(2026, 4, 1), date(2026, 4, 30), card_id=1) != a
    assert query_signature(date(2026, 4, 1), date(2026, 4, 30), card_type="T") != a
    assert query_signature(date(2026, 4, 1), date(2026, 4, 29)) != a
    # Whitespace around a filter value does not make a new signature.
    assert query_signature(date(2026, 4, 1), date(2026, 4, 30), bank=" X ") == query_signature(
        date(2026, 4, 1), date(2026, 4, 30), bank="X"
    )


def test_signature_depends_on_resolved_dates_not_on_how_they_were_asked_for():
    # month/absolute for April and custom for the same dates resolve equal.
    s1, e1 = resolve_period("month", "absolute", month="2026-04", today=TODAY)
    s2, e2 = resolve_period("custom", start="2026-04-01", end="2026-04-30", today=TODAY)
    assert (s1, e1) == (s2, e2)
    assert query_signature(s1, e1) == query_signature(s2, e2)
    # quarter Q2 vs custom Apr 1..Jun 30 likewise.
    s3, e3 = resolve_period("quarter", "absolute", quarter="2026-Q2", today=TODAY)
    s4, e4 = resolve_period("custom", start="2026-04-01", end="2026-06-30", today=TODAY)
    assert query_signature(s3, e3) == query_signature(s4, e4)
    # And a relative window that happens to land on the same dates as a custom one.
    s5, e5 = resolve_period("week", "relative", count=2, today=TODAY)
    s6, e6 = resolve_period("custom", start="2026-05-01", end="2026-05-15", today=TODAY)
    assert query_signature(s5, e5) == query_signature(s6, e6)


# --- narrow_payload ---------------------------------------------------------------


def test_narrow_payload_carries_only_period_total_and_category_amounts():
    # A deliberately over-rich aggregate: subcategories, transaction-level
    # fields, and unknown future keys. None of it may reach the model.
    aggregate = {
        "period": {"start": "2026-04-01", "end": "2026-04-30", "extra": "x"},
        "total": 140.0,
        "categories": [
            {
                "category": "Food",
                "amount": 100.0,
                "transaction_count": 1,
                "subcategories": [{"subcategory": "Cafe", "amount": 100.0, "transaction_count": 1}],
                "merchant": "SHOULD NOT LEAK",
                "description": "SHOULD NOT LEAK",
                "transactions": [{"id": 1, "description": "SHOULD NOT LEAK"}],
            },
            {"category": "Uncategorized", "amount": 40.0, "transaction_count": 1, "subcategories": []},
        ],
        "future_key": "SHOULD NOT LEAK",
    }
    payload = narrow_payload(aggregate)
    assert payload == {
        "period": {"start": "2026-04-01", "end": "2026-04-30"},
        "total": 140.0,
        "categories": [{"category": "Food", "amount": 100.0}, {"category": "Uncategorized", "amount": 40.0}],
    }
    # Belt and braces: the serialised form contains no leaked marker or key.
    import json

    text = json.dumps(payload)
    for forbidden in ("subcategor", "transaction", "merchant", "description", "LEAK", "future_key"):
        assert forbidden not in text


def test_payload_sent_to_gemini_is_the_narrowed_one(db_path, seeded, with_key, monkeypatch):
    fake = _fake_gemini()
    monkeypatch.setattr(com, "_call_gemini", fake)
    conn = get_connection()
    try:
        aggregate = agg.aggregate_spend(conn, date(2026, 5, 1), date(2026, 5, 31))
        assert aggregate["categories"][0]["subcategories"]  # the aggregate itself is rich
        generate_commentary(conn, aggregate, "sig")
    finally:
        conn.close()
    assert len(fake.calls) == 1
    sent = fake.calls[0]["payload"]
    assert set(sent.keys()) == {"period", "total", "categories"}
    assert all(set(c.keys()) == {"category", "amount"} for c in sent["categories"])
    assert fake.calls[0]["api_key"] == "fake-test-key"


# --- cache ------------------------------------------------------------------------


def test_upsert_replaces_rather_than_accumulating(db_path):
    conn = get_connection()
    try:
        assert get_cached(conn, "s") is None
        first = upsert_cached(conn, "s", "first")
        assert first["commentary"] == "first" and first["generated_at"]
        conn.execute(
            "UPDATE commentary_cache SET generated_at = '2020-01-01 00:00:00' WHERE query_signature = 's'"
        )
        conn.commit()
        second = upsert_cached(conn, "s", "second")
        assert second["commentary"] == "second"
        assert second["generated_at"] != "2020-01-01 00:00:00"  # refreshed on replace
        assert conn.execute("SELECT COUNT(*) FROM commentary_cache").fetchone()[0] == 1
        upsert_cached(conn, "t", "other")
        assert conn.execute("SELECT COUNT(*) FROM commentary_cache").fetchone()[0] == 2
    finally:
        conn.close()


# --- generate_commentary flow -------------------------------------------------------


def _aggregate_stub():
    return {"period": {"start": "2026-05-01", "end": "2026-05-31"}, "total": 1.0, "categories": []}


def test_missing_key_is_a_distinct_error_and_never_consults_the_cache(db_path, monkeypatch):
    monkeypatch.delenv(com.API_KEY_ENV, raising=False)
    monkeypatch.setattr(com, "_call_gemini", _failing_gemini())
    conn = get_connection()
    try:
        upsert_cached(conn, "sig", "cached text")  # present, but must not be returned
        with pytest.raises(CommentaryNotConfiguredError) as exc_info:
            generate_commentary(conn, _aggregate_stub(), "sig")
        assert "Gemini API key not configured" in str(exc_info.value)
    finally:
        conn.close()


def test_success_upserts_and_returns_fresh(db_path, with_key, monkeypatch):
    monkeypatch.setattr(com, "_call_gemini", _fake_gemini("Fresh words."))
    conn = get_connection()
    try:
        result = generate_commentary(conn, _aggregate_stub(), "sig")
        assert result["commentary"] == "Fresh words."
        assert result["cached"] is False
        assert result["generated_at"] == get_cached(conn, "sig")["generated_at"]
    finally:
        conn.close()


@pytest.mark.parametrize(
    "exc",
    [RuntimeError("network"), ValueError("unexpected Gemini response shape"), TimeoutError("slow")],
)
def test_failure_with_cache_returns_cached_row_and_its_own_timestamp(db_path, with_key, monkeypatch, exc):
    monkeypatch.setattr(com, "_call_gemini", _failing_gemini(exc))
    conn = get_connection()
    try:
        upsert_cached(conn, "sig", "older words")
        conn.execute(
            "UPDATE commentary_cache SET generated_at = '2026-01-02 03:04:05' WHERE query_signature = 'sig'"
        )
        conn.commit()
        result = generate_commentary(conn, _aggregate_stub(), "sig")
        assert result == {"commentary": "older words", "generated_at": "2026-01-02 03:04:05", "cached": True}
    finally:
        conn.close()


def test_failure_without_cache_raises_unavailable(db_path, with_key, monkeypatch):
    monkeypatch.setattr(com, "_call_gemini", _failing_gemini(RuntimeError("rate limited")))
    conn = get_connection()
    try:
        with pytest.raises(CommentaryUnavailableError) as exc_info:
            generate_commentary(conn, _aggregate_stub(), "sig")
        assert "nothing cached" in str(exc_info.value)
        assert get_cached(conn, "sig") is None  # a failure never writes
    finally:
        conn.close()


# --- endpoint ---------------------------------------------------------------------------


def _post(client, **params):
    return client.post("/analytics/commentary", params=params)


def test_endpoint_success_end_to_end(client, seeded, with_key, monkeypatch):
    fake = _fake_gemini("Food dominated.")
    monkeypatch.setattr(com, "_call_gemini", fake)
    response = _post(client, granularity="month", mode="absolute", month="2026-05")
    assert response.status_code == 200
    body = response.json()
    assert body["commentary"] == "Food dominated."
    assert body["cached"] is False
    assert body["generated_at"]
    sent = fake.calls[0]["payload"]
    assert sent["period"] == {"start": "2026-05-01", "end": "2026-05-31"}
    assert sent["total"] == 140.0
    assert {c["category"] for c in sent["categories"]} == {"Food", "Uncategorized"}
    assert all(set(c.keys()) == {"category", "amount"} for c in sent["categories"])
    # Second call for a view that resolves to the same dates via a different
    # spec: the same cache row is replaced, not duplicated.
    _post(client, granularity="custom", start="2026-05-01", end="2026-05-31")
    conn = get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM commentary_cache").fetchone()[0] == 1
    finally:
        conn.close()


def test_endpoint_missing_key_is_500_with_explicit_message(client, seeded, monkeypatch):
    monkeypatch.delenv(com.API_KEY_ENV, raising=False)
    response = _post(client, granularity="month", mode="absolute", month="2026-05")
    assert response.status_code == 500
    assert response.json()["detail"] == "Gemini API key not configured"


def test_endpoint_failure_paths(client, seeded, with_key, monkeypatch):
    monkeypatch.setattr(com, "_call_gemini", _failing_gemini())
    response = _post(client, granularity="month", mode="absolute", month="2026-05")
    assert response.status_code == 503
    assert "nothing cached" in response.json()["detail"]

    # Seed a cached row for exactly this resolved view, then fail again.
    conn = get_connection()
    try:
        sig = query_signature(date(2026, 5, 1), date(2026, 5, 31))
        upsert_cached(conn, sig, "from cache")
    finally:
        conn.close()
    response = _post(client, granularity="month", mode="absolute", month="2026-05")
    assert response.status_code == 200
    assert response.json()["commentary"] == "from cache"
    assert response.json()["cached"] is True


def test_endpoint_invalid_period_is_422_before_any_model_call(client, seeded, with_key, monkeypatch):
    fake = _fake_gemini()
    monkeypatch.setattr(com, "_call_gemini", fake)
    assert _post(client, granularity="week", mode="absolute").status_code == 422
    assert fake.calls == []


def test_endpoint_filters_change_the_signature(client, seeded, with_key, monkeypatch):
    monkeypatch.setattr(com, "_call_gemini", _fake_gemini())
    _post(client, granularity="month", mode="absolute", month="2026-05")
    _post(client, granularity="month", mode="absolute", month="2026-05", bank="FAKE BANK")
    conn = get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM commentary_cache").fetchone()[0] == 2
    finally:
        conn.close()
