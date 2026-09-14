import json
from datetime import date, datetime

import httpx
import pytest
from fastapi.testclient import TestClient

import parsers.llm_assist as llm
import storage.upload as upload_module
from main import app
from storage.cards import create_card
from storage.db import get_connection, init_db
from storage.reads import find_statement

# Session 100: the LLM-assisted parse. Every test replaces the model call;
# nothing here reaches the network. All statement content is fabricated.


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
def with_key(monkeypatch):
    monkeypatch.setenv(llm.API_KEY_ENV, "fake-key-for-tests")


@pytest.fixture
def without_key(monkeypatch):
    monkeypatch.delenv(llm.API_KEY_ENV, raising=False)


def _good_reply(**overrides):
    data = {
        "period_start": "2026-01-01",
        "period_end": "2026-01-31",
        "transactions": [
            {"date": "2026-01-05", "description": "FAKE SHOP ONE", "amount": 100.0, "type": "debit", "is_payment": False},
            {"date": "2026-01-10", "description": "FAKE SHOP TWO", "amount": 50, "type": "debit", "is_payment": False},
            {"date": "2026-01-15", "description": "PAYMENT RECEIVED", "amount": 75.0, "type": "credit", "is_payment": True},
        ],
        "summary": {"purchases_total": 150.0, "payments_credits_total": 75.0},
    }
    data.update(overrides)
    return json.dumps(data)


def _fake_call(reply):
    def fake(api_key, text):
        fake.calls.append((api_key, text))
        return reply
    fake.calls = []
    return fake


def _failing_call(exc):
    def fake(api_key, text):
        raise exc
    return fake


def _preview_llm(client, pdf_bytes, card_id):
    return client.post(
        "/upload/preview?strategy=llm_assist",
        files={"file": ("statement.pdf", pdf_bytes, "application/pdf")},
        data={"card_id": str(card_id)},
    )


# --- parse_reply(): the reply -> ParsedStatement contract ------------------


def test_parse_reply_well_formed():
    parsed, summary = llm.parse_reply(_good_reply())
    assert parsed["period_start"] == date(2026, 1, 1)
    assert parsed["period_end"] == date(2026, 1, 31)
    assert [(t["type"], t["amount"], t["is_payment"]) for t in parsed["transactions"]] == [
        ("debit", 100.0, False),
        ("debit", 50.0, False),
        ("credit", 75.0, True),
    ]
    assert parsed["transactions"][0]["date"] == datetime(2026, 1, 5)
    assert parsed["transactions"][0]["reward_points"] is None
    assert summary == {"purchases_total": 150.0, "payments_credits_total": 75.0}


def test_parse_reply_tolerates_markdown_fences():
    parsed, _ = llm.parse_reply("```json\n" + _good_reply() + "\n```")
    assert len(parsed["transactions"]) == 3


def test_parse_reply_summary_nulls_and_absent():
    _, summary = llm.parse_reply(_good_reply(summary={"purchases_total": None, "payments_credits_total": None}))
    assert summary == {"purchases_total": None, "payments_credits_total": None}
    _, summary = llm.parse_reply(_good_reply(summary=None))
    assert summary == {"purchases_total": None, "payments_credits_total": None}


def test_parse_reply_debit_is_never_a_payment():
    reply = _good_reply(transactions=[
        {"date": "2026-01-05", "description": "FAKE", "amount": 1.0, "type": "debit", "is_payment": True}
    ])
    parsed, _ = llm.parse_reply(reply)
    assert parsed["transactions"][0]["is_payment"] is False


@pytest.mark.parametrize(
    "reply, message",
    [
        ("not json at all", "not JSON"),
        ("[]", "not a JSON object"),
        (_good_reply(transactions="nope"), "transactions: expected a list"),
        (_good_reply(period_start="31/01/2026"), "period_start"),
        (_good_reply(period_end=None), "period_end"),
        (json.dumps({"period_start": "2026-01-01", "period_end": "2026-01-31", "transactions": ["x"]}), "transactions[0]"),
        (_good_reply(transactions=[{"date": "2026-01-05", "description": "", "amount": 1, "type": "debit"}]), "description"),
        (_good_reply(transactions=[{"date": "2026-01-05", "description": "X", "amount": 1, "type": "refund"}]), "type"),
        (_good_reply(transactions=[{"date": "2026-01-05", "description": "X", "amount": "1.00", "type": "debit"}]), "amount"),
        (_good_reply(transactions=[{"date": "2026-01-05", "description": "X", "amount": -1, "type": "debit"}]), "positive"),
        (_good_reply(transactions=[{"date": "2026-13-05", "description": "X", "amount": 1, "type": "debit"}]), "date"),
        (_good_reply(summary={"purchases_total": "150"}), "summary.purchases_total"),
        (_good_reply(summary=[1, 2]), "summary: expected an object"),
        ("", "not JSON"),
    ],
)
def test_parse_reply_rejects_malformed(reply, message):
    with pytest.raises(llm.LLMParseError) as excinfo:
        llm.parse_reply(reply)
    assert message in str(excinfo.value)


# --- redaction and the prompt -------------------------------------------------


def test_redact_long_digit_runs_but_not_amounts_or_dates():
    text = "Card 4111 111122223333 ref 000FAKE0000000000 XXXX XXXX 1234 total 1,08,110.00 on 05/01/2026"
    out = llm.redact(text)
    assert "111122223333" not in out
    assert "0000000000" not in out
    assert "1,08,110.00" in out
    assert "05/01/2026" in out
    assert "[number]" in out


def test_parse_with_summary_sends_redacted_text_and_key(make_pdf, tmp_path, with_key, monkeypatch):
    fake = _fake_call(_good_reply())
    monkeypatch.setattr(llm, "_call_gemini", fake)
    path = tmp_path / "s.pdf"
    path.write_bytes(make_pdf(["FAKE BANK statement acct 1234567890123456", "05/01/2026 FAKE SHOP 100.00"]))

    parsed, summary = llm.parse_with_summary(str(path), None)
    assert len(parsed["transactions"]) == 3
    [(api_key, text)] = fake.calls
    assert api_key == "fake-key-for-tests"
    assert "1234567890123456" not in text
    assert "FAKE SHOP 100.00" in text


def test_parse_with_summary_missing_key_never_calls(make_pdf, tmp_path, without_key, monkeypatch):
    fake = _fake_call(_good_reply())
    monkeypatch.setattr(llm, "_call_gemini", fake)
    path = tmp_path / "s.pdf"
    path.write_bytes(make_pdf(["x"]))
    with pytest.raises(llm.LLMNotConfiguredError) as excinfo:
        llm.parse_with_summary(str(path), None)
    assert "GEMINI_API_KEY" in str(excinfo.value)
    assert fake.calls == []


@pytest.mark.parametrize("exc", [httpx.ConnectError("down"), httpx.ReadTimeout("slow"), ValueError("shape")])
def test_parse_with_summary_call_failure_is_parse_error(make_pdf, tmp_path, with_key, monkeypatch, exc):
    monkeypatch.setattr(llm, "_call_gemini", _failing_call(exc))
    path = tmp_path / "s.pdf"
    path.write_bytes(make_pdf(["x"]))
    with pytest.raises(llm.LLMParseError) as excinfo:
        llm.parse_with_summary(str(path), None)
    assert type(exc).__name__ in str(excinfo.value)


def test_call_gemini_request_shape(monkeypatch):
    # The one test of the real HTTP function, against a mock transport:
    # model from env, key as a query param, JSON response mode requested,
    # the reply text returned.
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "{\"ok\": 1}"}]}}]})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(llm.httpx, "post", lambda url, **kw: httpx.Client(transport=transport).post(url, **kw))
    monkeypatch.setenv(llm.MODEL_ENV, "fake-model")

    assert llm._call_gemini("k", "statement text") == '{"ok": 1}'
    assert "models/fake-model:generateContent" in seen["url"]
    assert "key=k" in seen["url"]
    assert seen["body"]["generationConfig"] == {"responseMimeType": "application/json"}
    assert "statement text" in seen["body"]["contents"][0]["parts"][0]["text"]


# --- through the preview endpoint --------------------------------------------


@pytest.fixture
def card(conn):
    return create_card(conn, "FAKE BANK", "Platinum")


def test_preview_llm_well_formed_reconciles_and_confirms(client, conn, card, make_pdf, with_key, monkeypatch):
    monkeypatch.setattr(llm, "_call_gemini", _fake_call(_good_reply()))
    body = _preview_llm(client, make_pdf(["FAKE BANK statement"]), card).json()
    assert body["status"] == "preview"
    assert body["strategy"] == "llm_assist"
    assert body["transaction_count"] == 3
    assert body["period_start"] == "2026-01-01"
    # Sums are computed here from the rows; the model's totals are the expected side.
    assert body["reconciliation"] == {
        "status": "match",
        "debit": {"expected": 150.0, "parsed": 150.0, "delta": 0.0},
        "credit": {"expected": 75.0, "parsed": 75.0, "delta": 0.0},
    }
    confirm = client.post("/upload/confirm", json={"upload_id": body["upload_id"]})
    assert confirm.status_code == 200
    statement = find_statement(conn, card, date(2026, 1, 1), date(2026, 1, 31))
    rows = conn.execute(
        "SELECT txn_type, amount, is_payment FROM transactions WHERE statement_id = ? ORDER BY id",
        (statement["id"],),
    ).fetchall()
    assert [tuple(r) for r in rows] == [("debit", 100.0, 0), ("debit", 50.0, 0), ("credit", 75.0, 1)]


def test_preview_llm_mismatch_goes_through_the_gate(client, card, make_pdf, with_key, monkeypatch):
    monkeypatch.setattr(llm, "_call_gemini", _fake_call(_good_reply(summary={"purchases_total": 999.0, "payments_credits_total": 75.0})))
    body = _preview_llm(client, make_pdf(["x"]), card).json()
    assert body["reconciliation"]["status"] == "mismatch"
    assert client.post("/upload/confirm", json={"upload_id": body["upload_id"]}).status_code == 422
    assert client.post("/upload/confirm", json={"upload_id": body["upload_id"], "override_reconciliation": True}).status_code == 200


def test_preview_llm_no_totals_is_mismatch(client, card, make_pdf, with_key, monkeypatch):
    monkeypatch.setattr(llm, "_call_gemini", _fake_call(_good_reply(summary=None)))
    body = _preview_llm(client, make_pdf(["x"]), card).json()
    assert body["reconciliation"]["status"] == "mismatch"
    assert body["reconciliation"]["debit"]["expected"] is None


def test_preview_llm_malformed_reply_is_clean_status(client, card, make_pdf, with_key, monkeypatch):
    monkeypatch.setattr(llm, "_call_gemini", _fake_call("Sorry, I cannot do that."))
    response = _preview_llm(client, make_pdf(["x"]), card)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "llm_failed"
    assert "not JSON" in body["reason"]
    assert upload_module.PREVIEWS == {}


def test_preview_llm_call_failure_is_clean_status(client, card, make_pdf, with_key, monkeypatch):
    monkeypatch.setattr(llm, "_call_gemini", _failing_call(httpx.ConnectError("down")))
    body = _preview_llm(client, make_pdf(["x"]), card).json()
    assert body == {"status": "llm_failed", "reason": "model call failed: ConnectError"}


def test_preview_llm_missing_key_is_clean_status(client, card, make_pdf, without_key, monkeypatch):
    fake = _fake_call(_good_reply())
    monkeypatch.setattr(llm, "_call_gemini", fake)
    body = _preview_llm(client, make_pdf(["x"]), card).json()
    assert body == {"status": "llm_not_configured", "api_key_env": "GEMINI_API_KEY"}
    assert fake.calls == []


def test_preview_llm_locked_pdf_is_password_needed_before_any_call(client, card, with_key, monkeypatch):
    from pdfminer.pdfdocument import PDFPasswordIncorrect
    from pdfplumber.utils.exceptions import PdfminerException

    import parsers.detect as detect_module

    fake = _fake_call(_good_reply())
    monkeypatch.setattr(llm, "_call_gemini", fake)
    monkeypatch.setattr(
        detect_module, "_first_page_text",
        lambda p, pw: (_ for _ in ()).throw(PdfminerException(PDFPasswordIncorrect())),
    )
    body = _preview_llm(client, b"%PDF-1.4 locked", card).json()
    assert body["status"] == "password_needed"
    assert fake.calls == []


def test_preview_llm_duplicate_is_hard_stop(client, conn, card, make_pdf, with_key, monkeypatch):
    from storage.writes import insert_statement

    insert_statement(conn, card, date(2026, 1, 1), date(2026, 1, 31), [])
    monkeypatch.setattr(llm, "_call_gemini", _fake_call(_good_reply()))
    assert _preview_llm(client, make_pdf(["x"]), card).json()["status"] == "duplicate"
