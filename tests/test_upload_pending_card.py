from datetime import date

import pytest
from fastapi.testclient import TestClient

import storage.upload as upload_module
import storage.writes as writes_module
from main import app
from storage.cards import CardAlreadyExistsError, create_card, find_cards_for_type, list_cards
from storage.db import get_connection, init_db
from storage.reads import find_statement
from storage.writes import insert_statement, insert_statement_with_new_card
from tests.test_upload_preview import _confirm, _hdfc_statement

# Session 112: a card entered during upload is created only when the import
# is confirmed, atomically with its statement. All content fabricated.


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


def _preview_new(client, pdf_bytes, bank="HDFC", card_type="Diners", nickname="Primary", extra=None, strategy=None):
    data = {"new_bank": bank, "new_card_type": card_type}
    if nickname is not None:
        data["new_nickname"] = nickname
    data.update(extra or {})
    url = "/upload/preview" + (f"?strategy={strategy}" if strategy else "")
    return client.post(url, files={"file": ("s.pdf", pdf_bytes, "application/pdf")}, data=data)


def _rows():
    return [{"txn_date": date(2026, 1, 5), "description": "X", "amount": 1.0, "txn_type": "debit", "reward_points": None}]


# --- storage: the atomic write ---------------------------------------------------


def test_new_card_write_creates_both(conn):
    card_id, statement_id = insert_statement_with_new_card(
        conn, "HDFC", "Diners", "Primary", date(2026, 1, 1), date(2026, 1, 31), _rows()
    )
    [card] = find_cards_for_type(conn, "HDFC", "Diners")
    assert card["card_id"] == card_id and card["nickname"] == "Primary"
    assert find_statement(conn, card_id, date(2026, 1, 1), date(2026, 1, 31))["id"] == statement_id
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1


def test_new_card_write_nickname_collision_writes_nothing(conn):
    create_card(conn, "HDFC", "Diners", "Primary")
    before = conn.execute("SELECT COUNT(*) FROM statements").fetchone()[0]
    with pytest.raises(CardAlreadyExistsError):
        insert_statement_with_new_card(
            conn, "HDFC", "Diners", "Primary", date(2026, 1, 1), date(2026, 1, 31), _rows()
        )
    assert len(list_cards(conn)) == 1
    assert conn.execute("SELECT COUNT(*) FROM statements").fetchone()[0] == before


def test_new_card_write_row_failure_rolls_the_card_back(conn):
    bad_rows = [{"txn_date": date(2026, 1, 5), "description": None, "amount": 1.0, "txn_type": "debit"}]
    with pytest.raises(Exception):
        insert_statement_with_new_card(
            conn, "HDFC", "Diners", "Primary", date(2026, 1, 1), date(2026, 1, 31), bad_rows
        )
    assert list_cards(conn) == []
    assert conn.execute("SELECT COUNT(*) FROM statements").fetchone()[0] == 0


def test_new_card_write_failure_after_card_insert_rolls_back(conn, monkeypatch):
    # A failure between the two inserts, simulated: no card survives it.
    def boom(*args, **kwargs):
        raise RuntimeError("simulated failure between the two inserts")

    monkeypatch.setattr(writes_module, "_insert_statement_rows", boom)
    with pytest.raises(RuntimeError):
        insert_statement_with_new_card(
            conn, "HDFC", "Diners", "Primary", date(2026, 1, 1), date(2026, 1, 31), _rows()
        )
    assert list_cards(conn) == []


# --- preview with a pending card ---------------------------------------------------


def test_preview_pending_card_creates_nothing(client, conn, make_pdf):
    response = _preview_new(client, make_pdf(_hdfc_statement()))
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["status"] == "preview"
    assert body["card_id"] is None
    assert body["new_card"] == {"bank": "HDFC", "card_type": "Diners", "nickname": "Primary"}
    assert body["reconciliation"]["status"] == "match"
    assert list_cards(conn) == []  # nothing created yet


def test_preview_pending_card_without_nickname(client, make_pdf):
    body = _preview_new(client, make_pdf(_hdfc_statement()), nickname=None).json()
    assert body["new_card"]["nickname"] is None
    body = _preview_new(client, make_pdf(_hdfc_statement()), nickname="   ").json()
    assert body["new_card"]["nickname"] is None


def test_preview_pending_card_skips_duplicate_check(client, conn, make_pdf):
    # The same period exists on another card of the same bank/type; a card
    # that does not exist yet cannot hold it, so no duplicate.
    other = create_card(conn, "HDFC", "Diners", "Other")
    insert_statement(conn, other, date(2026, 1, 1), date(2026, 1, 31), [])
    body = _preview_new(client, make_pdf(_hdfc_statement()), nickname="New").json()
    assert body["status"] == "preview"


def test_preview_pending_card_strips_and_validates(client, make_pdf):
    body = _preview_new(client, make_pdf(_hdfc_statement()), bank="  HDFC ", card_type=" Diners ").json()
    assert body["new_card"]["bank"] == "HDFC" and body["new_card"]["card_type"] == "Diners"
    assert _preview_new(client, make_pdf(_hdfc_statement()), bank="  ", card_type="Diners").status_code == 422
    response = client.post(
        "/upload/preview", files={"file": ("s.pdf", make_pdf(_hdfc_statement()), "application/pdf")},
        data={"new_bank": "HDFC"},  # no card type
    )
    assert response.status_code == 422


def test_preview_requires_exactly_one_of_card_id_or_new_card(client, conn, make_pdf):
    card = create_card(conn, "HDFC", "Diners")
    neither = client.post("/upload/preview", files={"file": ("s.pdf", make_pdf(_hdfc_statement()), "application/pdf")})
    assert neither.status_code == 422
    both = _preview_new(client, make_pdf(_hdfc_statement()), extra={"card_id": str(card)})
    assert both.status_code == 422
    assert "exactly one" in both.json()["detail"]


def test_preview_pending_card_password_needed_names_its_bank(client, make_pdf, monkeypatch, no_statement_passwords):
    from pdfminer.pdfdocument import PDFPasswordIncorrect
    from pdfplumber.utils.exceptions import PdfminerException

    import parsers.detect as detect_module

    monkeypatch.setattr(detect_module, "_first_page_text",
                        lambda p, pw: (_ for _ in ()).throw(PdfminerException(PDFPasswordIncorrect())))
    body = _preview_new(client, b"%PDF-1.4 locked", bank="ICICI", card_type="Coral").json()
    assert body["status"] == "password_needed"
    assert body["bank"] == "ICICI" and body["password_env_key"] == "ICICI_SAMPLE_PASSWORD"


def test_preview_pending_card_unknown_bank_best_effort(client, conn, make_pdf):
    lines = ["FAKE BANK statement", "Statement Period: 01/01/2026 to 31/01/2026", "05/01/2026 FAKE SHOP 10.00"]
    body = _preview_new(client, make_pdf(lines), bank="Axis", card_type="Magnus", strategy="best_effort").json()
    assert body["status"] == "preview" and body["new_card"]["bank"] == "Axis"
    assert list_cards(conn) == []


def test_preview_pending_card_bank_without_parser_detected_strategy_is_422(client, make_pdf):
    assert _preview_new(client, make_pdf(_hdfc_statement()), bank="Axis", card_type="Magnus").status_code == 422


# --- confirm with a pending card -------------------------------------------------------


def test_confirm_pending_card_creates_card_and_statement(client, conn, make_pdf):
    upload_id = _preview_new(client, make_pdf(_hdfc_statement())).json()["upload_id"]
    assert list_cards(conn) == []
    response = _confirm(client, upload_id)
    assert response.status_code == 200, response.json()
    body = response.json()
    [card] = list_cards(conn)
    assert card["id"] == body["card_id"]
    assert (card["bank"], card["card_type"], card["nickname"]) == ("HDFC", "Diners", "Primary")
    statement = find_statement(conn, card["id"], date(2026, 1, 1), date(2026, 1, 31))
    assert statement["id"] == body["statement_id"]
    assert body["transaction_count"] == 3
    assert upload_id not in upload_module.PREVIEWS


def test_confirm_pending_card_mismatch_still_gated(client, conn, make_pdf):
    upload_id = _preview_new(client, make_pdf(_hdfc_statement(purchases="999.00"))).json()["upload_id"]
    assert _confirm(client, upload_id).status_code == 422
    assert list_cards(conn) == []  # declined: no orphan
    assert _confirm(client, upload_id, override=True).status_code == 200
    assert len(list_cards(conn)) == 1


def test_confirm_pending_card_nickname_collision_is_409_and_writes_nothing(client, conn, make_pdf):
    upload_id = _preview_new(client, make_pdf(_hdfc_statement())).json()["upload_id"]
    create_card(conn, "HDFC", "Diners", "Primary")  # someone took the name meanwhile
    response = _confirm(client, upload_id)
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]
    assert len(list_cards(conn)) == 1
    assert conn.execute("SELECT COUNT(*) FROM statements").fetchone()[0] == 0
    assert upload_id in upload_module.PREVIEWS  # still held: change the details and retry


def test_confirm_pending_card_failure_leaves_no_orphan(db_path, conn, make_pdf, monkeypatch):
    client = TestClient(app, raise_server_exceptions=False)
    upload_id = _preview_new(client, make_pdf(_hdfc_statement())).json()["upload_id"]

    def boom(*args, **kwargs):
        raise RuntimeError("simulated failure after the card insert")

    monkeypatch.setattr(writes_module, "_insert_statement_rows", boom)
    assert _confirm(client, upload_id).status_code == 500
    assert list_cards(conn) == []
    assert conn.execute("SELECT COUNT(*) FROM statements").fetchone()[0] == 0


def test_preview_never_created_leaves_nothing(client, conn, make_pdf):
    # The original gap: back out after preview -> no card.
    _preview_new(client, make_pdf(_hdfc_statement()))
    _preview_new(client, make_pdf(_hdfc_statement()), nickname="Second")
    assert list_cards(conn) == []


# --- existing card_id flows unchanged ---------------------------------------------------


def test_existing_card_flow_unchanged(client, conn, make_pdf):
    card = create_card(conn, "HDFC", "Diners", "Primary")  # matched / multi-match / picked
    response = client.post(
        "/upload/preview", files={"file": ("s.pdf", make_pdf(_hdfc_statement()), "application/pdf")},
        data={"card_id": str(card)},
    )
    body = response.json()
    assert body["status"] == "preview" and body["card_id"] == card and body["new_card"] is None
    confirm = _confirm(client, body["upload_id"]).json()
    assert confirm["card_id"] == card
    assert len(list_cards(conn)) == 1


def test_existing_zero_statement_card_still_duplicate_checked(client, conn, make_pdf):
    card = create_card(conn, "HDFC", "Diners", "Primary")
    insert_statement(conn, card, date(2026, 1, 1), date(2026, 1, 31), [])
    response = client.post(
        "/upload/preview", files={"file": ("s.pdf", make_pdf(_hdfc_statement()), "application/pdf")},
        data={"card_id": str(card)},
    )
    assert response.json()["status"] == "duplicate"
