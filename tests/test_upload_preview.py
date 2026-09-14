from datetime import date

import pytest
from fastapi.testclient import TestClient

import storage.upload as upload_module
from main import app
from parsers.reconcile import reconcile
from storage.cards import create_card
from storage.db import get_connection, init_db
from storage.reads import find_statement
from storage.writes import insert_statement

# Session 98: POST /upload/preview and POST /upload/confirm. The synthetic
# statements below are HDFC current-layout text (landmark, billing period,
# the "=" summary line, "_" total line, transaction rows) so the *real*
# hdfc_diners parser and summary extraction run end to end. All merchants and
# amounts are fabricated.


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


@pytest.fixture
def card_id(conn):
    return create_card(conn, "HDFC", "Diners", "Primary")


def _hdfc_statement(purchases="150.00", credits="75.00"):
    # Two debits (100 + 50) and one credit (75): the summary line carries
    # previous dues, credits received, purchases, finance charges.
    return [
        "Statement for HDFC Bank Credit Card",
        "PAYMENTS/CREDITS PURCHASES/DEBITS",
        "Billing Period 01 Jan, 2026 - 31 Jan, 2026",
        f"C 0.00 C {credits} C {purchases} C 0.00 =",
        "_ C 75.00",
        "05/01/2026| 10:00 FAKE SHOP ONE C 100.00 l",
        "10/01/2026| 11:00 FAKE SHOP TWO C 50.00 l",
        "15/01/2026| 12:00 PAYMENT RECEIVED THANK YOU + C 75.00 l",
    ]


def _preview(client, pdf_bytes, card_id):
    return client.post(
        "/upload/preview",
        files={"file": ("statement.pdf", pdf_bytes, "application/pdf")},
        data={"card_id": str(card_id)},
    )


def _confirm(client, upload_id, override=None):
    body = {"upload_id": upload_id}
    if override is not None:
        body["override_reconciliation"] = override
    return client.post("/upload/confirm", json=body)


# --- reconcile() -----------------------------------------------------------


def _txns():
    return [
        {"type": "debit", "amount": 100.0},
        {"type": "debit", "amount": 50.0},
        {"type": "credit", "amount": 75.0},
    ]


def test_reconcile_match():
    assert reconcile(_txns(), 150.0, 75.0) == {
        "status": "match",
        "debit": {"expected": 150.0, "parsed": 150.0, "delta": 0.0},
        "credit": {"expected": 75.0, "parsed": 75.0, "delta": 0.0},
    }


def test_reconcile_one_side_off_is_mismatch():
    result = reconcile(_txns(), 150.0, 80.0)
    assert result["status"] == "mismatch"
    assert result["debit"]["delta"] == 0.0
    assert result["credit"]["delta"] == -5.0


def test_reconcile_within_a_paisa_matches():
    assert reconcile(_txns(), 150.004, 75.0)["status"] == "match"


def test_reconcile_missing_summary_figure_is_mismatch():
    result = reconcile(_txns(), None, 75.0)
    assert result["status"] == "mismatch"
    assert result["debit"] == {"expected": None, "parsed": 150.0, "delta": None}


# --- preview -----------------------------------------------------------------


def test_preview_clean(client, conn, card_id, make_pdf):
    response = _preview(client, make_pdf(_hdfc_statement()), card_id)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "preview"
    assert body["card_id"] == card_id
    assert body["period_start"] == "2026-01-01"
    assert body["period_end"] == "2026-01-31"
    assert body["transaction_count"] == 3
    assert body["reconciliation"]["status"] == "match"
    assert body["reconciliation"]["debit"]["expected"] == 150.0
    assert body["reconciliation"]["credit"]["expected"] == 75.0
    assert body["upload_id"] in upload_module.PREVIEWS
    # Nothing written yet.
    assert find_statement(conn, card_id, date(2026, 1, 1), date(2026, 1, 31)) is None


def test_preview_mismatch_reports_both_sides(client, card_id, make_pdf):
    body = _preview(client, make_pdf(_hdfc_statement(purchases="999.00")), card_id).json()
    assert body["status"] == "preview"
    assert body["reconciliation"]["status"] == "mismatch"
    assert body["reconciliation"]["debit"] == {"expected": 999.0, "parsed": 150.0, "delta": -849.0}
    assert body["reconciliation"]["credit"]["delta"] == 0.0


def test_preview_duplicate_is_hard_stop(client, conn, card_id, make_pdf):
    statement_id = insert_statement(conn, card_id, date(2026, 1, 1), date(2026, 1, 31), [])
    body = _preview(client, make_pdf(_hdfc_statement()), card_id).json()
    assert body == {
        "status": "duplicate",
        "card_id": card_id,
        "statement_id": statement_id,
        "period_start": "2026-01-01",
        "period_end": "2026-01-31",
    }
    assert upload_module.PREVIEWS == {}  # nothing cached: there is nothing to confirm


def test_preview_same_period_other_card_is_not_duplicate(client, conn, card_id, make_pdf):
    other = create_card(conn, "HDFC", "Diners", "Add-on")
    insert_statement(conn, other, date(2026, 1, 1), date(2026, 1, 31), [])
    assert _preview(client, make_pdf(_hdfc_statement()), card_id).json()["status"] == "preview"


def test_preview_unknown_card(client, make_pdf):
    response = _preview(client, make_pdf(_hdfc_statement()), 999)
    assert response.status_code == 404


def test_preview_bank_without_parser(client, conn, make_pdf):
    card = create_card(conn, "FAKE BANK", "Whatever")
    response = _preview(client, make_pdf(_hdfc_statement()), card)
    assert response.status_code == 422
    assert "No parser configured" in response.json()["detail"]


def test_preview_card_type_without_parser(client, conn, make_pdf):
    card = create_card(conn, "HDFC", "Regalia")
    response = _preview(client, make_pdf(_hdfc_statement()), card)
    assert response.status_code == 422
    assert "not yet implemented" in response.json()["detail"]


def test_preview_unreadable_period(client, card_id, make_pdf):
    lines = [l for l in _hdfc_statement() if not l.startswith("Billing Period")]
    response = _preview(client, make_pdf(lines), card_id)
    assert response.status_code == 422
    assert "statement period" in response.json()["detail"]


def test_preview_non_pdf(client, card_id):
    response = _preview(client, b"not a pdf", card_id)
    assert response.status_code == 422


def test_preview_requires_card_id(client, make_pdf):
    response = client.post(
        "/upload/preview", files={"file": ("s.pdf", make_pdf(["x"]), "application/pdf")}
    )
    assert response.status_code == 422


# --- confirm -----------------------------------------------------------------


def test_confirm_clean_writes_and_clears(client, conn, card_id, make_pdf):
    upload_id = _preview(client, make_pdf(_hdfc_statement()), card_id).json()["upload_id"]
    response = _confirm(client, upload_id)
    assert response.status_code == 200
    body = response.json()
    assert body["transaction_count"] == 3
    statement = find_statement(conn, card_id, date(2026, 1, 1), date(2026, 1, 31))
    assert statement["id"] == body["statement_id"]
    rows = conn.execute(
        "SELECT txn_type, amount FROM transactions WHERE statement_id = ? ORDER BY id",
        (statement["id"],),
    ).fetchall()
    assert [tuple(r) for r in rows] == [("debit", 100.0), ("debit", 50.0), ("credit", 75.0)]
    assert upload_id not in upload_module.PREVIEWS


def test_confirm_twice_is_expired(client, card_id, make_pdf):
    upload_id = _preview(client, make_pdf(_hdfc_statement()), card_id).json()["upload_id"]
    assert _confirm(client, upload_id).status_code == 200
    response = _confirm(client, upload_id)
    assert response.status_code == 410
    assert "expired" in response.json()["detail"]


def test_confirm_unknown_upload_id_is_expired(client):
    response = _confirm(client, "no-such-preview")
    assert response.status_code == 410


def test_confirm_mismatch_blocked_by_default(client, conn, card_id, make_pdf):
    upload_id = _preview(client, make_pdf(_hdfc_statement(purchases="999.00")), card_id).json()["upload_id"]
    response = _confirm(client, upload_id)
    assert response.status_code == 422
    assert "override_reconciliation" in response.json()["detail"]
    assert upload_id in upload_module.PREVIEWS  # still confirmable
    assert find_statement(conn, card_id, date(2026, 1, 1), date(2026, 1, 31)) is None


def test_confirm_mismatch_explicit_false_still_blocked(client, card_id, make_pdf):
    upload_id = _preview(client, make_pdf(_hdfc_statement(purchases="999.00")), card_id).json()["upload_id"]
    assert _confirm(client, upload_id, override=False).status_code == 422


def test_confirm_mismatch_overridden(client, conn, card_id, make_pdf):
    upload_id = _preview(client, make_pdf(_hdfc_statement(purchases="999.00")), card_id).json()["upload_id"]
    response = _confirm(client, upload_id, override=True)
    assert response.status_code == 200
    assert response.json()["transaction_count"] == 3
    assert find_statement(conn, card_id, date(2026, 1, 1), date(2026, 1, 31)) is not None


def test_confirm_raced_duplicate_is_409_and_dropped(client, conn, card_id, make_pdf):
    # Previewed clean, then the same statement lands by another route (the
    # CLI) before confirm: insert_statement dedups, confirm reports it.
    upload_id = _preview(client, make_pdf(_hdfc_statement()), card_id).json()["upload_id"]
    insert_statement(conn, card_id, date(2026, 1, 1), date(2026, 1, 31), [])
    response = _confirm(client, upload_id, override=True)
    assert response.status_code == 409
    assert upload_id not in upload_module.PREVIEWS


def test_confirm_requires_upload_id(client):
    assert client.post("/upload/confirm", json={}).status_code == 422


# --- real samples (skip without the local PDFs and .env passwords) ---------
# The one promise nothing above checks: that the registry's summary keys are
# the right two for each bank. Each real sample previews with a matching
# reconciliation, exactly as its own test_<bank>_real_statements.py asserts
# by hand. Counts and statuses only in the assertions, never content.

import os
from pathlib import Path

from parsers.registry import BANKS
from tests.test_upload_detect import _REAL_CASES


@pytest.mark.parametrize("bank, pdf_path", _REAL_CASES)
def test_real_statement_previews_reconciled(bank, pdf_path, client, conn):
    if not os.environ.get(BANKS[bank].password_env_key):
        pytest.skip(f"{BANKS[bank].password_env_key} not set in .env")
    if not Path(pdf_path).exists():
        pytest.skip(f"{pdf_path} not present locally")

    card = create_card(conn, bank, BANKS[bank].card_type)
    body = _preview(client, Path(pdf_path).read_bytes(), card).json()
    assert body["status"] == "preview"
    assert body["transaction_count"] > 0
    assert body["reconciliation"]["status"] == "match", body["reconciliation"]["status"]
