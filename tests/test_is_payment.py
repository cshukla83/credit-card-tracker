"""is_payment: schema, per-bank detection, and the assign cascade (Session 61).

All bank names, merchants, and amounts in the unit tests below are fabricated.
The per-bank detection tests read the real sample statements (git-ignored,
password from .env) and assert counts only -- never a description, amount,
or date.
"""

import os
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient

import parsers.hdfc as hdfc_dispatch
import parsers.icici as icici_dispatch
import parsers.indusind as indusind_dispatch
import parsers.sbi as sbi_dispatch
from main import app
from parsers.base import is_payment_credit
from storage.cards import create_card
from storage.categories import (
    PAYMENT_LABEL,
    InvalidPaymentFlagError,
    assign_categories,
)
from storage.db import get_connection, init_db
from storage.writes import insert_statement

load_dotenv()


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setenv("DB_PATH", str(path))
    init_db()
    return str(path)


@pytest.fixture
def client(db_path):
    return TestClient(app)


def _txn(day, description, txn_type="debit", is_payment=None):
    row = {
        "txn_date": date(2026, 1, day),
        "description": description,
        "amount": 10.0,
        "txn_type": txn_type,
        "reward_points": None,
    }
    if is_payment is not None:
        row["is_payment"] = is_payment
    return row


def _seed(conn, rows, bank="FAKE BANK"):
    """One card of `bank`, one statement, the given rows. Returns ids in order."""
    card_id = create_card(conn, bank, "FAKE CARD TYPE")
    insert_statement(conn, card_id, date(2026, 1, 1), date(2026, 1, 31), rows)
    return [r["id"] for r in conn.execute("SELECT id FROM transactions ORDER BY id")]


def _state(conn, ids):
    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(
        "SELECT id, category, subcategory, merchant, is_payment FROM transactions "
        f"WHERE id IN ({placeholders}) ORDER BY id",
        ids,
    ).fetchall()
    return [(r["category"], r["subcategory"], r["merchant"], r["is_payment"]) for r in rows]


# --- schema / migration -------------------------------------------------------


def test_fresh_db_has_not_null_boolean_is_payment(db_path):
    conn = get_connection()
    try:
        cols = {row["name"]: row for row in conn.execute("PRAGMA table_xinfo(transactions)")}
        assert cols["is_payment"]["type"] == "INTEGER"
        assert cols["is_payment"]["notnull"] == 1
        assert cols["is_payment"]["dflt_value"] == "0"
    finally:
        conn.close()


def test_is_payment_migration_is_idempotent_and_backfills_zero(tmp_path, monkeypatch):
    # Pre-Session-61 schema: every column up to merchant, no is_payment.
    path = tmp_path / "legacy.db"
    monkeypatch.setenv("DB_PATH", str(path))
    legacy = sqlite3.connect(str(path))
    legacy.executescript(
        """
        CREATE TABLE cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT, bank TEXT NOT NULL, card_type TEXT NOT NULL,
            nickname TEXT, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(bank, card_type, nickname));
        CREATE TABLE statements (
            id INTEGER PRIMARY KEY AUTOINCREMENT, card_id INTEGER NOT NULL,
            period_start DATE NOT NULL, period_end DATE NOT NULL,
            imported_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(card_id) REFERENCES cards(id) ON DELETE CASCADE,
            UNIQUE(card_id, period_start, period_end));
        CREATE TABLE transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, statement_id INTEGER NOT NULL,
            txn_date DATE NOT NULL, description TEXT NOT NULL, amount REAL NOT NULL,
            txn_type TEXT NOT NULL, reward_points REAL, category TEXT, subcategory TEXT,
            merchant TEXT,
            FOREIGN KEY(statement_id) REFERENCES statements(id) ON DELETE CASCADE);
        INSERT INTO cards (bank, card_type) VALUES ('FAKE BANK', 'FAKE CARD TYPE');
        INSERT INTO statements (card_id, period_start, period_end)
            VALUES (1, '2026-01-01', '2026-01-31');
        INSERT INTO transactions (statement_id, txn_date, description, amount, txn_type)
            VALUES (1, '2026-01-05', 'LEGACY ROW', 10.0, 'credit');
        """
    )
    legacy.commit()
    legacy.close()

    init_db()
    init_db()  # second run must not raise

    conn = get_connection()
    try:
        cols = {row["name"] for row in conn.execute("PRAGMA table_xinfo(transactions)")}
        assert "is_payment" in cols
        row = conn.execute("SELECT is_payment FROM transactions").fetchone()
        assert row["is_payment"] == 0  # back-filled with the default, not NULL
    finally:
        conn.close()


# --- the shared prefix rule ----------------------------------------------------


def test_is_payment_credit_rule():
    prefixes = ("PAY TOKEN", "OTHER TOKEN")
    assert is_payment_credit("credit", "PAY TOKEN 123", prefixes)
    assert is_payment_credit("credit", "  pay token x", prefixes)  # case, leading space
    assert is_payment_credit("credit", "other token", prefixes)
    assert not is_payment_credit("credit", "XPAY TOKEN", prefixes)  # prefix, not substring
    assert not is_payment_credit("credit", "REFUND FROM SHOP", prefixes)
    assert not is_payment_credit("debit", "PAY TOKEN 123", prefixes)  # never for debits


def test_insert_defaults_is_payment_to_zero_and_stores_flag(db_path):
    conn = get_connection()
    try:
        ids = _seed(
            conn,
            [
                _txn(1, "A"),  # no key at all -> 0
                _txn(2, "B", "credit", is_payment=True),
                _txn(3, "C", "credit", is_payment=False),
            ],
        )
        assert [s[3] for s in _state(conn, ids)] == [0, 1, 0]
    finally:
        conn.close()


# --- per-bank detection against the real samples ------------------------------
# Counts only. Each bank's samples were inspected in Session 61; the expected
# numbers are how many credit rows are payments to the card vs. refunds.

_BANKS = {
    # (dispatch, card_type, env key, [(path, total credits, payment credits), ...])
    "HDFC": (
        hdfc_dispatch, "Diners", "HDFC_SAMPLE_PASSWORD",
        [
            ("data/statements/hdfc_sample.pdf", 1, 1),
            ("data/statements/hdfc_sample_2.pdf", 2, 1),
            ("data/statements/hdfc_sample_3.pdf", 1, 1),
            ("data/statements/hdfc_sample_4.PDF", 1, 1),  # legacy layout
            ("data/statements/hdfc_sample_5.PDF", 2, 2),  # legacy layout, two channels
            ("data/statements/hdfc_sample_6.pdf", 2, 2),
        ],
    ),
    "ICICI": (
        icici_dispatch, "Coral", "ICICI_SAMPLE_PASSWORD",
        [
            ("data/statements/icici_sample.pdf", 2, 1),
            ("data/statements/icici_sample_2.pdf", 1, 1),
            ("data/statements/icici_sample_3.pdf", 1, 1),
            ("data/statements/icici_sample_4.pdf", 1, 1),
        ],
    ),
    "SBI": (
        sbi_dispatch, "Titan", "SBI_SAMPLE_PASSWORD",
        [
            ("data/statements/sbi_sample.pdf", 5, 1),
            ("data/statements/sbi_sample_2.pdf", 2, 1),
            ("data/statements/sbi_sample_3.pdf", 2, 1),
            ("data/statements/sbi_sample_4.pdf", 4, 1),
        ],
    ),
    "IndusInd": (
        indusind_dispatch, "Legend", "INDUSIND_SAMPLE_PASSWORD",
        [
            ("data/statements/IndusInd_sample.pdf", 2, 1),
            ("data/statements/IndusInd_sample_2.pdf", 1, 1),
            ("data/statements/IndusInd_sample_3.pdf", 2, 1),
            ("data/statements/IndusInd_sample_4.pdf", 1, 1),
        ],
    ),
}

_CASES = [
    pytest.param(bank, path, credits, payments, id=f"{bank}-{Path(path).stem}")
    for bank, (_, _, _, samples) in _BANKS.items()
    for path, credits, payments in samples
]


@pytest.mark.parametrize("bank, pdf_path, expected_credits, expected_payments", _CASES)
def test_real_statement_payment_detection(bank, pdf_path, expected_credits, expected_payments):
    dispatch, card_type, env_key, _ = _BANKS[bank]
    password = os.environ.get(env_key)
    if not password:
        pytest.skip(f"{env_key} not set in .env")
    if not Path(pdf_path).exists():
        pytest.skip(f"{pdf_path} not present locally")

    parsed = dispatch.parse(pdf_path, password, card_type=card_type)
    credits = [t for t in parsed["transactions"] if t["type"] == "credit"]
    payments = [t for t in credits if t["is_payment"]]
    debits_flagged = [t for t in parsed["transactions"] if t["type"] == "debit" and t["is_payment"]]

    assert len(credits) == expected_credits
    assert len(payments) == expected_payments
    assert debits_flagged == []
    # Every transaction carries the key, as a real bool.
    assert all(isinstance(t["is_payment"], bool) for t in parsed["transactions"])


# --- cascade ---------------------------------------------------------------------


def test_cascade_zero_to_one_writes_labels_and_bank_merchant(db_path):
    conn = get_connection()
    try:
        (a,) = _seed(conn, [_txn(1, "SOME CREDIT", "credit")], bank="FAKE BANK")
        assign_categories(conn, [(a, "Food", "Cafe", "Shop", None)])  # pre-existing labels
        assert assign_categories(conn, [(a, None, None, None, True)]) == 1
        assert _state(conn, [a]) == [(PAYMENT_LABEL, PAYMENT_LABEL, "FAKE BANK", 1)]
    finally:
        conn.close()


def test_cascade_merchant_is_bank_name_verbatim_not_title_cased(db_path):
    conn = get_connection()
    try:
        (a,) = _seed(conn, [_txn(1, "SOME CREDIT", "credit")], bank="HDFC")
        assign_categories(conn, [(a, None, None, None, True)])
        assert _state(conn, [a])[0][2] == "HDFC"
    finally:
        conn.close()


def test_cascade_one_to_zero_reverts_labels_to_null(db_path):
    conn = get_connection()
    try:
        (a,) = _seed(conn, [_txn(1, "SOME CREDIT", "credit")])
        assign_categories(conn, [(a, None, None, None, True)])
        assert assign_categories(conn, [(a, None, None, None, False)]) == 1
        assert _state(conn, [a]) == [(None, None, None, 0)]
    finally:
        conn.close()


def test_same_value_is_a_noop_and_does_not_retrigger_cascade(db_path):
    conn = get_connection()
    try:
        (a,) = _seed(conn, [_txn(1, "SOME CREDIT", "credit")])
        # Already 0: sending 0 changes nothing and counts nothing.
        assert assign_categories(conn, [(a, None, None, None, False)]) == 0
        assert _state(conn, [a]) == [(None, None, None, 0)]
        # Flag it, then hand-edit the labels; re-sending 1 must not clobber them.
        assign_categories(conn, [(a, None, None, None, True)])
        assign_categories(conn, [(a, "Food", "Cafe", "Shop", None)])
        assert assign_categories(conn, [(a, None, None, None, True)]) == 0
        assert _state(conn, [a]) == [("Food", "Cafe", "Shop", 1)]
    finally:
        conn.close()


def test_noop_flag_alongside_another_field_still_writes_that_field(db_path):
    conn = get_connection()
    try:
        (a,) = _seed(conn, [_txn(1, "SOME CREDIT", "credit")])
        assert assign_categories(conn, [(a, "Food", None, None, False)]) == 1
        assert _state(conn, [a]) == [("Food", None, None, 0)]
    finally:
        conn.close()


def test_flagging_a_debit_is_rejected_and_nothing_is_written(db_path):
    conn = get_connection()
    try:
        d, c = _seed(conn, [_txn(1, "A DEBIT", "debit"), _txn(2, "A CREDIT", "credit")])
        with pytest.raises(InvalidPaymentFlagError) as exc_info:
            # Valid credit entry first, invalid debit entry second: atomic.
            assign_categories(
                conn, [(c, None, None, None, True), (d, "Food", None, None, True)]
            )
        assert exc_info.value.invalid_ids == [d]
        assert _state(conn, [d, c]) == [(None, None, None, 0), (None, None, None, 0)]
        # Un-flagging a debit is harmless (it is already 0): a no-op, not an error.
        assert assign_categories(conn, [(d, None, None, None, False)]) == 0
    finally:
        conn.close()


def test_cascade_is_atomic_with_an_unknown_id(db_path):
    conn = get_connection()
    try:
        (c,) = _seed(conn, [_txn(1, "A CREDIT", "credit")])
        with pytest.raises(Exception):
            assign_categories(conn, [(c, None, None, None, True), (9999, None, None, None, True)])
        assert _state(conn, [c]) == [(None, None, None, 0)]
    finally:
        conn.close()


def test_cascade_is_atomic_when_a_later_update_fails(db_path):
    # Force the UPDATE phase to fail partway: the flag's own UPDATE must roll
    # back with it. sqlite3.Connection methods can't be monkeypatched, so a
    # proxy delegates `with` and every call, and raises on the second UPDATE.
    conn = get_connection()
    try:
        a, b = _seed(conn, [_txn(1, "CREDIT ONE", "credit"), _txn(2, "CREDIT TWO", "credit")])

        class Flaky:
            def __init__(self, real):
                self._real = real
                self.updates = 0

            def __enter__(self):
                return self._real.__enter__()

            def __exit__(self, *exc):
                return self._real.__exit__(*exc)

            def execute(self, sql, *args, **kwargs):
                if sql.lstrip().upper().startswith("UPDATE"):
                    self.updates += 1
                    if self.updates == 2:
                        raise sqlite3.OperationalError("simulated failure")
                return self._real.execute(sql, *args, **kwargs)

        flaky = Flaky(conn)
        with pytest.raises(sqlite3.OperationalError):
            # Two different field-sets -> two UPDATE statements.
            assign_categories(flaky, [(a, None, None, None, True), (b, "Food", None, None, None)])
        assert flaky.updates == 2  # the first UPDATE really ran before the failure
        assert _state(conn, [a, b]) == [(None, None, None, 0), (None, None, None, 0)]
    finally:
        conn.close()


def test_explicit_field_conflicting_with_cascade_is_rejected(db_path):
    conn = get_connection()
    try:
        (c,) = _seed(conn, [_txn(1, "A CREDIT", "credit")])
        with pytest.raises(ValueError):
            assign_categories(conn, [(c, "Food", None, None, True)])
        # Agreeing with the cascade is fine.
        assert assign_categories(conn, [(c, PAYMENT_LABEL, None, None, True)]) == 1
        assert _state(conn, [c])[0][3] == 1
    finally:
        conn.close()


# --- endpoint --------------------------------------------------------------------


def _seed_via_db(bank="FAKE BANK"):
    conn = get_connection()
    try:
        return _seed(
            conn,
            [_txn(1, "A DEBIT", "debit"), _txn(2, "A CREDIT", "credit")],
            bank=bank,
        )
    finally:
        conn.close()


def _rows(client):
    return {t["id"]: t for t in client.get("/transactions").json()}


def test_endpoint_cascade_both_directions(client):
    d, c = _seed_via_db(bank="FAKE BANK")
    response = client.post(
        "/transactions/category",
        json={"assignments": [{"transaction_id": c, "is_payment": True}]},
    )
    assert response.status_code == 200
    assert response.json() == {"updated": 1}
    row = _rows(client)[c]
    assert (row["category"], row["subcategory"], row["merchant"], row["is_payment"]) == (
        PAYMENT_LABEL, PAYMENT_LABEL, "FAKE BANK", 1,
    )
    response = client.post(
        "/transactions/category",
        json={"assignments": [{"transaction_id": c, "is_payment": False}]},
    )
    assert response.status_code == 200
    row = _rows(client)[c]
    assert (row["category"], row["subcategory"], row["merchant"], row["is_payment"]) == (
        None, None, None, 0,
    )


def test_endpoint_rejects_flagging_a_debit_with_400_and_writes_nothing(client):
    d, c = _seed_via_db()
    response = client.post(
        "/transactions/category",
        json={
            "assignments": [
                {"transaction_id": c, "is_payment": True},
                {"transaction_id": d, "is_payment": True},
            ]
        },
    )
    assert response.status_code == 400
    assert str(d) in response.json()["detail"]
    rows = _rows(client)
    assert rows[c]["is_payment"] == 0 and rows[c]["category"] is None
    assert rows[d]["is_payment"] == 0


def test_endpoint_is_payment_alone_satisfies_at_least_one_field(client):
    d, c = _seed_via_db()
    assert client.post(
        "/transactions/category",
        json={"assignments": [{"transaction_id": c, "is_payment": False}]},
    ).status_code == 200  # a no-op, but a valid request
    assert client.post(
        "/transactions/category",
        json={"assignments": [{"transaction_id": c}]},
    ).status_code == 422


def test_endpoint_noop_repeat_does_not_reclobber_labels(client):
    d, c = _seed_via_db()
    client.post("/transactions/category", json={"assignments": [{"transaction_id": c, "is_payment": True}]})
    client.post("/transactions/category", json={"assignments": [{"transaction_id": c, "category": "Food"}]})
    response = client.post(
        "/transactions/category", json={"assignments": [{"transaction_id": c, "is_payment": True}]}
    )
    assert response.json() == {"updated": 0}
    assert _rows(client)[c]["category"] == "Food"
