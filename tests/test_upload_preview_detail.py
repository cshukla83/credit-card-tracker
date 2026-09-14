from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

import storage.upload as upload_module
from main import app
from storage.cards import create_card
from storage.categories import suggest_categories_for_descriptions
from storage.db import get_connection, init_db
from storage.upload import NO_SUGGESTION, PendingUpload, preview_detail
from storage.writes import insert_statement

# Session 103: GET /upload/{upload_id}/preview-detail. Every description,
# category and amount here is fabricated.


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
def conn(db_path):
    c = get_connection()
    yield c
    c.close()


@pytest.fixture(autouse=True)
def clear_previews():
    upload_module.PREVIEWS.clear()
    yield
    upload_module.PREVIEWS.clear()


def _row(day, description, amount=10.0, txn_type="debit"):
    return {
        "date": datetime(2026, 1, day),
        "description": description,
        "amount": amount,
        "type": txn_type,
        "reward_points": None,
        "is_payment": False,
    }


def _hold(rows, card_id=1, upload_id="held"):
    parsed = {"period_start": date(2026, 1, 1), "period_end": date(2026, 1, 31), "transactions": rows}
    upload_module.PREVIEWS[upload_id] = PendingUpload(
        card_id=card_id, new_card=None, parsed=parsed, reconciliation={"status": "match"}
    )
    return upload_id


def _labelled(conn, description, category):
    """One categorised row already in the DB, for the engine to learn from."""
    card = create_card(conn, "FAKE BANK", "FAKE", description)  # unique nickname per call
    statement_id = insert_statement(
        conn, card, date(2025, 12, 1), date(2025, 12, 31),
        [{"txn_date": date(2025, 12, 5), "description": description, "amount": 1.0, "txn_type": "debit", "reward_points": None}],
    )
    conn.execute("UPDATE transactions SET category = ? WHERE statement_id = ?", (category, statement_id))
    conn.commit()


# --- sampling -----------------------------------------------------------------


def test_short_statement_samples_overlap(conn):
    upload_id = _hold([_row(d, f"ROW {d}") for d in range(1, 8)])  # 7 rows
    detail = preview_detail(conn, upload_id)
    assert detail["total_rows"] == 7
    assert [r["description"] for r in detail["sample_start"]] == ["ROW 1", "ROW 2", "ROW 3", "ROW 4", "ROW 5"]
    assert [r["description"] for r in detail["sample_end"]] == ["ROW 3", "ROW 4", "ROW 5", "ROW 6", "ROW 7"]


def test_exactly_ten_rows_cover_everything_without_overlap(conn):
    upload_id = _hold([_row(d, f"ROW {d}") for d in range(1, 11)])
    detail = preview_detail(conn, upload_id)
    starts = [r["description"] for r in detail["sample_start"]]
    ends = [r["description"] for r in detail["sample_end"]]
    assert starts + ends == [f"ROW {d}" for d in range(1, 11)]


def test_long_statement_samples_do_not_overlap(conn):
    upload_id = _hold([_row(1 + d % 28, f"ROW {d}") for d in range(1, 24)])  # 23 rows
    detail = preview_detail(conn, upload_id)
    assert detail["total_rows"] == 23
    assert [r["description"] for r in detail["sample_start"]] == [f"ROW {d}" for d in range(1, 6)]
    assert [r["description"] for r in detail["sample_end"]] == [f"ROW {d}" for d in range(19, 24)]


def test_fewer_than_five_rows(conn):
    upload_id = _hold([_row(1, "ONLY"), _row(2, "TWO")])
    detail = preview_detail(conn, upload_id)
    assert len(detail["sample_start"]) == 2
    assert len(detail["sample_end"]) == 2


def test_empty_statement(conn):
    upload_id = _hold([])
    detail = preview_detail(conn, upload_id)
    assert detail == {
        "upload_id": upload_id, "total_rows": 0, "sample_start": [], "sample_end": [], "category_breakdown": [],
    }


def test_sample_row_shape(conn):
    upload_id = _hold([_row(5, "FAKE SHOP", 12.5, "credit")])
    [row] = preview_detail(conn, upload_id)["sample_start"]
    assert row == {"date": "2026-01-05", "description": "FAKE SHOP", "amount": 12.5, "type": "credit"}


# --- category breakdown ---------------------------------------------------------


def test_breakdown_groups_by_suggestion_and_counts_no_suggestion(conn):
    _labelled(conn, "FAKE GROCER", "Groceries")
    _labelled(conn, "FAKE FUEL STOP", "Fuel")
    upload_id = _hold([
        _row(1, "FAKE GROCER"),          # exact -> Groceries
        _row(2, "fake grocer"),          # exact, case-insensitive -> Groceries
        _row(3, "FAKE GROCER"),          # exact -> Groceries
        _row(4, "FAKE FUEL STOP"),       # exact -> Fuel
        _row(5, "ZZZ UNRELATED 9"),      # fuzzy -> one of the two, low confidence, still counted
    ])
    breakdown = preview_detail(conn, upload_id)["category_breakdown"]
    counts = {b["category"]: b["count"] for b in breakdown}
    assert counts["Groceries"] >= 3
    assert counts["Fuel"] >= 1
    assert sum(counts.values()) == 5
    assert breakdown[0]["category"] == "Groceries"  # most frequent first


def test_breakdown_cold_start_is_all_no_suggestion(conn):
    upload_id = _hold([_row(1, "A"), _row(2, "B"), _row(3, "C")])
    detail = preview_detail(conn, upload_id)
    assert detail["category_breakdown"] == [{"category": NO_SUGGESTION, "count": 3}]


def test_breakdown_runs_over_every_row_not_just_the_samples(conn):
    _labelled(conn, "FAKE GROCER", "Groceries")
    rows = [_row(1 + d % 28, "UNLABELLED THING") for d in range(20)]
    rows[10] = _row(11, "FAKE GROCER")  # only in the middle -- outside both samples
    upload_id = _hold(rows)
    detail = preview_detail(conn, upload_id)
    assert "FAKE GROCER" not in [r["description"] for r in detail["sample_start"] + detail["sample_end"]]
    counts = {b["category"]: b["count"] for b in detail["category_breakdown"]}
    assert counts["Groceries"] >= 1
    assert sum(counts.values()) == 20


def test_breakdown_writes_nothing(conn):
    _labelled(conn, "FAKE GROCER", "Groceries")
    before = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    upload_id = _hold([_row(1, "FAKE GROCER")])
    preview_detail(conn, upload_id)
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == before
    assert upload_id in upload_module.PREVIEWS  # still confirmable


def test_suggest_for_descriptions_matches_engine_shape(conn):
    _labelled(conn, "FAKE GROCER", "Groceries")
    [hit, miss] = suggest_categories_for_descriptions(conn, ["FAKE GROCER", "ZZZ 1"])
    assert hit["value"] == "Groceries" and hit["match_type"] == "exact" and hit["confidence"] == 1.0
    assert set(miss) == {"value", "confidence", "match_type"}


# --- endpoint -------------------------------------------------------------------


def test_endpoint_returns_detail(client, conn):
    upload_id = _hold([_row(d, f"ROW {d}") for d in range(1, 13)])
    response = client.get(f"/upload/{upload_id}/preview-detail")
    assert response.status_code == 200
    body = response.json()
    assert body["total_rows"] == 12
    assert len(body["sample_start"]) == 5 and len(body["sample_end"]) == 5
    assert body["category_breakdown"] == [{"category": NO_SUGGESTION, "count": 12}]


def test_endpoint_unknown_upload_id_is_410_like_confirm(client):
    response = client.get("/upload/no-such/preview-detail")
    assert response.status_code == 410
    assert response.json()["detail"] == client.post("/upload/confirm", json={"upload_id": "no-such"}).json()["detail"]


def test_endpoint_after_confirm_is_410(client, conn):
    card = create_card(conn, "HDFC", "Diners")
    upload_id = _hold([_row(1, "X")], card_id=card)
    assert client.post("/upload/confirm", json={"upload_id": upload_id}).status_code == 200
    assert client.get(f"/upload/{upload_id}/preview-detail").status_code == 410
