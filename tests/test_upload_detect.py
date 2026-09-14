import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from main import app
from parsers.detect import PasswordNeededError, identify, unlock
from parsers.registry import BANKS
from storage.cards import create_card, find_cards_for_type
from storage.db import get_connection, init_db
from storage.upload import resolve_card
from storage.writes import insert_statement
from datetime import date

# Session 97: POST /cards and POST /upload/detect. Every bank name, nickname
# and statement line below is fabricated. The real-sample tests at the bottom
# skip unless the git-ignored PDFs and their .env passwords are present.


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


def _upload(client, pdf_bytes, filename="statement.pdf"):
    return client.post("/upload/detect", files={"file": (filename, pdf_bytes, "application/pdf")})


# --- identify(): landmark matching on page-1 text ---------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Statement for HDFC Bank Credit Card", ("HDFC", "Diners")),
        ("Your ICICI Bank Credit Card statement", ("ICICI", "Coral")),
        ("SBI Card statement of account", ("SBI", "Titan")),
        ("INDUSIND BANK LEGEND CREDIT CARD STATEMENT", ("IndusInd", "Legend")),
    ],
)
def test_identify_each_bank(text, expected):
    assert identify(text) == expected


def test_identify_is_case_insensitive():
    assert identify("hdfc bank credit card") == ("HDFC", "Diners")


def test_identify_unknown_text_is_none():
    assert identify("Some Other Bank Platinum statement") is None


def test_identify_sbi_landmark_needs_word_boundary():
    # "BCSBI" (a regulator's acronym on an HDFC page) must not read as SBI.
    assert identify("member of BCSBI") is None


def test_identify_two_banks_on_one_page_is_ambiguous():
    assert identify("HDFC Bank Credit Card and ICICI Bank Credit Card") is None


# --- unlock(): password attempts -------------------------------------------


def test_unlock_reads_unencrypted_pdf_without_password(make_pdf, tmp_path):
    path = tmp_path / "s.pdf"
    path.write_bytes(make_pdf(["FAKE BANK statement", "second line"]))
    unlocked = unlock(str(path))
    assert unlocked.password is None
    assert unlocked.first_page_text == "FAKE BANK statement\nsecond line"


def test_unlock_raises_password_needed_listing_tried_keys(monkeypatch, tmp_path):
    from pdfminer.pdfdocument import PDFPasswordIncorrect
    from pdfplumber.utils.exceptions import PdfminerException

    import parsers.detect as detect_module

    tried = []

    def fake_first_page_text(pdf_path, password):
        tried.append(password)
        raise PdfminerException(PDFPasswordIncorrect())

    monkeypatch.setattr(detect_module, "_first_page_text", fake_first_page_text)
    for bank in BANKS.values():
        monkeypatch.delenv(bank.password_env_key, raising=False)
    monkeypatch.setenv("SBI_SAMPLE_PASSWORD", "fake-sbi")

    with pytest.raises(PasswordNeededError) as excinfo:
        unlock(str(tmp_path / "locked.pdf"))
    assert tried == [None, "fake-sbi"]
    assert excinfo.value.tried_env_keys == ["SBI_SAMPLE_PASSWORD"]


# --- resolve_card(): the three DB outcomes ---------------------------------


def test_resolve_zero_match(conn):
    assert resolve_card(conn, "HDFC", "Diners") == {
        "status": "zero_match",
        "bank": "HDFC",
        "card_type": "Diners",
    }


def test_resolve_matched(conn):
    card_id = create_card(conn, "HDFC", "Diners", "Primary")
    assert resolve_card(conn, "HDFC", "Diners") == {
        "status": "matched",
        "card_id": card_id,
        "bank": "HDFC",
        "card_type": "Diners",
    }


def test_resolve_matched_is_case_insensitive(conn):
    card_id = create_card(conn, "hdfc", "diners")
    assert resolve_card(conn, "HDFC", "Diners")["card_id"] == card_id


def test_resolve_multi_match_with_last_periods(conn):
    a = create_card(conn, "HDFC", "Diners", "Primary")
    b = create_card(conn, "HDFC", "Diners", "Add-on")
    create_card(conn, "ICICI", "Coral", "Other bank")  # must not appear
    insert_statement(conn, a, date(2026, 1, 1), date(2026, 1, 31), [])
    insert_statement(conn, a, date(2026, 2, 1), date(2026, 2, 28), [])

    result = resolve_card(conn, "HDFC", "Diners")
    assert result["status"] == "multi_match"
    assert result["candidates"] == [
        {
            "card_id": a,
            "bank": "HDFC",
            "card_type": "Diners",
            "nickname": "Primary",
            "last_statement_period": {"period_start": "2026-02-01", "period_end": "2026-02-28"},
        },
        {
            "card_id": b,
            "bank": "HDFC",
            "card_type": "Diners",
            "nickname": "Add-on",
            "last_statement_period": None,
        },
    ]


def test_find_cards_for_type_latest_period_by_period_end(conn):
    a = create_card(conn, "SBI", "Titan")
    insert_statement(conn, a, date(2026, 3, 1), date(2026, 3, 31), [])
    insert_statement(conn, a, date(2026, 1, 1), date(2026, 1, 31), [])
    [card] = find_cards_for_type(conn, "SBI", "Titan")
    assert card["last_statement_period"] == {"period_start": "2026-03-01", "period_end": "2026-03-31"}


# --- POST /upload/detect ----------------------------------------------------


def test_detect_matched(client, conn, make_pdf):
    card_id = create_card(conn, "ICICI", "Coral")
    response = _upload(client, make_pdf(["ICICI Bank Credit Card Statement"]))
    assert response.status_code == 200
    assert response.json() == {
        "status": "matched",
        "card_id": card_id,
        "bank": "ICICI",
        "card_type": "Coral",
    }


def test_detect_zero_match(client, make_pdf):
    response = _upload(client, make_pdf(["SBI Card monthly statement"]))
    assert response.json() == {"status": "zero_match", "bank": "SBI", "card_type": "Titan"}


def test_detect_multi_match(client, conn, make_pdf):
    create_card(conn, "IndusInd", "Legend", "One")
    create_card(conn, "IndusInd", "Legend", "Two")
    body = _upload(client, make_pdf(["IndusInd Bank Legend Credit Card"])).json()
    assert body["status"] == "multi_match"
    assert [c["nickname"] for c in body["candidates"]] == ["One", "Two"]


def test_detect_unrecognized(client, make_pdf):
    response = _upload(client, make_pdf(["FAKE BANK Platinum statement"]))
    assert response.status_code == 200
    assert response.json() == {"status": "unrecognized"}


def test_detect_password_needed(client, monkeypatch):
    from pdfminer.pdfdocument import PDFPasswordIncorrect
    from pdfplumber.utils.exceptions import PdfminerException

    import parsers.detect as detect_module

    monkeypatch.setattr(
        detect_module,
        "_first_page_text",
        lambda path, password: (_ for _ in ()).throw(PdfminerException(PDFPasswordIncorrect())),
    )
    for bank in BANKS.values():
        monkeypatch.delenv(bank.password_env_key, raising=False)
    monkeypatch.setenv("HDFC_SAMPLE_PASSWORD", "x")

    body = _upload(client, b"%PDF-1.4 locked").json()
    assert body == {
        "status": "password_needed",
        "bank": None,
        "card_type": None,
        "tried_env_keys": ["HDFC_SAMPLE_PASSWORD"],
    }


def test_detect_rejects_non_pdf(client):
    response = _upload(client, b"hello, not a pdf", filename="notes.txt")
    assert response.status_code == 422
    assert "PDF" in response.json()["detail"]


def test_detect_requires_file(client):
    assert client.post("/upload/detect").status_code == 422


# --- POST /cards -------------------------------------------------------------


def test_create_card(client, conn):
    response = client.post("/cards", json={"bank": "HDFC", "card_type": "Diners", "nickname": "Primary"})
    assert response.status_code == 201
    body = response.json()
    assert body["bank"] == "HDFC"
    assert body["card_type"] == "Diners"
    assert body["nickname"] == "Primary"
    assert [c["card_id"] for c in find_cards_for_type(conn, "HDFC", "Diners")] == [body["id"]]


def test_create_card_without_nickname(client):
    response = client.post("/cards", json={"bank": "SBI", "card_type": "Titan"})
    assert response.status_code == 201
    assert response.json()["nickname"] is None


def test_create_card_conflict(client):
    payload = {"bank": "HDFC", "card_type": "Diners", "nickname": "Primary"}
    assert client.post("/cards", json=payload).status_code == 201
    response = client.post("/cards", json=payload)
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


def test_create_card_strips_and_rejects_blank(client):
    response = client.post("/cards", json={"bank": "  HDFC ", "card_type": "Diners", "nickname": "  Main "})
    assert response.status_code == 201
    assert response.json()["bank"] == "HDFC"
    assert response.json()["nickname"] == "Main"
    assert client.post("/cards", json={"bank": "  ", "card_type": "Diners"}).status_code == 422
    assert client.post("/cards", json={"bank": "HDFC"}).status_code == 422


# --- real samples (skip without the local PDFs and .env passwords) ---------

_REAL = {
    "HDFC": ["hdfc_sample.pdf", "hdfc_sample_2.pdf", "hdfc_sample_3.pdf",
             "hdfc_sample_4.PDF", "hdfc_sample_5.PDF", "hdfc_sample_6.pdf"],
    "ICICI": ["icici_sample.pdf", "icici_sample_2.pdf", "icici_sample_3.pdf", "icici_sample_4.pdf"],
    "SBI": ["sbi_sample.pdf", "sbi_sample_2.pdf", "sbi_sample_3.pdf", "sbi_sample_4.pdf"],
    "IndusInd": ["IndusInd_sample.pdf", "IndusInd_sample_2.pdf",
                 "IndusInd_sample_3.pdf", "IndusInd_sample_4.pdf"],
}
_REAL_CASES = [
    pytest.param(bank, f"data/statements/{name}", id=f"{bank}-{Path(name).stem}")
    for bank, names in _REAL.items()
    for name in names
]


@pytest.mark.parametrize("bank, pdf_path", _REAL_CASES)
def test_real_statement_detected_as_its_bank(bank, pdf_path, client):
    if not os.environ.get(BANKS[bank].password_env_key):
        pytest.skip(f"{BANKS[bank].password_env_key} not set in .env")
    if not Path(pdf_path).exists():
        pytest.skip(f"{pdf_path} not present locally")

    body = _upload(client, Path(pdf_path).read_bytes()).json()
    assert body == {"status": "zero_match", "bank": bank, "card_type": BANKS[bank].card_type}
