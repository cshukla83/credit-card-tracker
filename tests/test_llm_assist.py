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
        "balance_summary": [
            {"label": "Purchases", "amount": 120.0, "side": "debit"},
            {"label": "Fees & Charges", "amount": 30, "side": "debit"},
            {"label": "Payments Received", "amount": 75.0, "side": "credit"},
        ],
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
    assert summary == {"total_debits": 150.0, "total_credits": 75.0}


def test_parse_reply_tolerates_markdown_fences():
    parsed, _ = llm.parse_reply("```json\n" + _good_reply() + "\n```")
    assert len(parsed["transactions"]) == 3


# --- balance_summary (Session 114): components summed here, per side ---------


def test_balance_summary_components_are_summed_per_side():
    _, summary = llm.parse_reply(_good_reply(balance_summary=[
        {"label": "Purchase", "amount": 1000.5, "side": "debit"},
        {"label": "Other Debit&Charges", "amount": 99.25, "side": "debit"},
        {"label": "Interest", "amount": 0.25, "side": "debit"},
        {"label": "Payment", "amount": 500, "side": "credit"},
        {"label": "Refund", "amount": 12.5, "side": "credit"},
    ]))
    assert summary == {"total_debits": 1100.0, "total_credits": 512.5}


def test_balance_summary_empty_means_both_totals_null():
    _, summary = llm.parse_reply(_good_reply(balance_summary=[]))
    assert summary == {"total_debits": None, "total_credits": None}


def test_balance_summary_one_side_only_leaves_other_null():
    _, summary = llm.parse_reply(_good_reply(balance_summary=[
        {"label": "Purchases", "amount": 10, "side": "debit"},
    ]))
    assert summary == {"total_debits": 10.0, "total_credits": None}


def test_balance_summary_sum_avoids_float_drift():
    _, summary = llm.parse_reply(_good_reply(balance_summary=[
        {"label": "a", "amount": 0.1, "side": "debit"},
        {"label": "b", "amount": 0.2, "side": "debit"},
    ]))
    assert summary["total_debits"] == 0.3


@pytest.mark.parametrize(
    "component, message",
    [
        ({"amount": 1, "side": "debit"}, "balance_summary[0].label"),
        ({"label": "", "amount": 1, "side": "debit"}, "balance_summary[0].label"),
        ({"label": "x", "amount": 1, "side": "dr"}, "balance_summary[0].side"),
        ({"label": "x", "amount": 1}, "balance_summary[0].side"),
        ({"label": "x", "amount": -1, "side": "debit"}, "balance_summary[0].amount"),
        ({"label": "x", "amount": "1.00", "side": "debit"}, "balance_summary[0].amount"),
        ({"label": "x", "side": "debit"}, "balance_summary[0].amount"),
        ("not an object", "balance_summary[0]: expected an object"),
    ],
)
def test_balance_summary_rejects_invalid_component(component, message):
    with pytest.raises(llm.LLMParseError) as excinfo:
        llm.parse_reply(_good_reply(balance_summary=[component]))
    assert message in str(excinfo.value)


def test_balance_summary_invalid_component_names_its_index():
    good = {"label": "ok", "amount": 1, "side": "debit"}
    with pytest.raises(llm.LLMParseError) as excinfo:
        llm.parse_reply(_good_reply(balance_summary=[good, good, {"label": "x", "amount": 1, "side": "both"}]))
    assert "balance_summary[2].side" in str(excinfo.value)


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
        (_good_reply(balance_summary={"total_debits": 150}), "balance_summary: expected a list"),
        (_good_reply(balance_summary=None), "balance_summary: expected a list"),
        (json.dumps({"period_start": "2026-01-01", "period_end": "2026-01-31", "transactions": []}), "balance_summary: expected a list"),
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


def _http_status_error(status_code):
    request = httpx.Request("POST", "https://example.invalid/generateContent")
    response = httpx.Response(status_code, request=request, json={"error": {"message": "x"}})
    return httpx.HTTPStatusError("boom", request=request, response=response)


@pytest.mark.parametrize("status_code", [429, 500, 400])
def test_http_error_reason_carries_status_code(make_pdf, tmp_path, with_key, monkeypatch, status_code):
    # Session 102: a transient 429/503 must be tellable from a rejected
    # request, and the body never leaks into the reason.
    monkeypatch.setattr(llm, "_call_gemini", _failing_call(_http_status_error(status_code)))
    path = tmp_path / "s.pdf"
    path.write_bytes(make_pdf(["x"]))
    with pytest.raises(llm.LLMParseError) as excinfo:
        llm.parse_with_summary(str(path), None)
    assert str(excinfo.value) == f"model call failed: HTTPStatusError {status_code}"


def test_http_error_status_reaches_the_llm_failed_body(client, card, make_pdf, with_key, monkeypatch):
    monkeypatch.setattr(llm, "_call_gemini", _failing_call(_http_status_error(503)))
    body = _preview_llm(client, make_pdf(["x"]), card).json()
    assert body == {"status": "llm_failed", "reason": "model call failed: HTTPStatusError 503"}


def test_default_model_is_used_when_env_is_unset(monkeypatch):
    # Session 102: the default was never exercised before -- the local .env
    # always sets GEMINI_MODEL -- and the old one was not a callable model.
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "{}"}]}}]})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(llm.httpx, "post", lambda url, **kw: httpx.Client(transport=transport).post(url, **kw))
    monkeypatch.delenv(llm.MODEL_ENV, raising=False)

    llm._call_gemini("k", "text")
    assert llm.DEFAULT_MODEL == "gemini-3.5-flash"
    assert "models/gemini-3.5-flash:generateContent" in seen["url"]


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
    # Components that sum to the wrong debit total: mismatch, not unverified.
    monkeypatch.setattr(llm, "_call_gemini", _fake_call(_good_reply(balance_summary=[
        {"label": "Purchases", "amount": 900.0, "side": "debit"},
        {"label": "Fees", "amount": 99.0, "side": "debit"},
        {"label": "Payments", "amount": 75.0, "side": "credit"},
    ])))
    body = _preview_llm(client, make_pdf(["x"]), card).json()
    assert body["reconciliation"]["status"] == "mismatch"
    assert body["reconciliation"]["debit"] == {"expected": 999.0, "parsed": 150.0, "delta": -849.0}
    assert client.post("/upload/confirm", json={"upload_id": body["upload_id"]}).status_code == 422
    assert client.post("/upload/confirm", json={"upload_id": body["upload_id"], "override_reconciliation": True}).status_code == 200


def test_preview_llm_no_summary_box_is_unverified(client, card, make_pdf, with_key, monkeypatch):
    # Session 114: an empty balance_summary is "no summary box found" --
    # unverified, gated like a mismatch, overridable like one.
    monkeypatch.setattr(llm, "_call_gemini", _fake_call(_good_reply(balance_summary=[])))
    body = _preview_llm(client, make_pdf(["x"]), card).json()
    assert body["reconciliation"]["status"] == "unverified"
    assert body["reconciliation"]["debit"] == {"expected": None, "parsed": 150.0, "delta": None}
    assert body["reconciliation"]["credit"] == {"expected": None, "parsed": 75.0, "delta": None}
    assert client.post("/upload/confirm", json={"upload_id": body["upload_id"]}).status_code == 422
    assert client.post("/upload/confirm", json={"upload_id": body["upload_id"], "override_reconciliation": True}).status_code == 200


def test_preview_llm_credit_side_missing_is_unverified(client, card, make_pdf, with_key, monkeypatch):
    monkeypatch.setattr(llm, "_call_gemini", _fake_call(_good_reply(balance_summary=[
        {"label": "Purchases", "amount": 150.0, "side": "debit"},
    ])))
    body = _preview_llm(client, make_pdf(["x"]), card).json()
    assert body["reconciliation"]["status"] == "unverified"
    assert body["reconciliation"]["debit"]["delta"] == 0.0
    assert body["reconciliation"]["credit"]["expected"] is None


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
