"""LLM-assisted statement parse (Session 100).

For a PDF no registry landmark recognises, as the alternative to the
best-attempt heuristics in generic_fallback: the statement's extracted text
goes to the model with a fixed JSON schema to fill, and the reply becomes a
ParsedStatement -- the same contract as every other parser, through the
same preview / reconciliation / confirm path. A one-off parse of this one
file: no format is learned, nothing is cached for the next upload (the Tier
4 auto-learn system in PRODUCT_VISION.md is a different, later thing).

The model is also asked for the statement's own printed totals, so the
parsed sums have something to reconcile against; the sums themselves are
always computed here from the returned rows, never taken from the model.

**This is the second place data leaves the machine**, after the dashboard
commentary, and unlike that one the payload cannot be narrowed: the point
is to read the statement, so descriptions, dates and amounts all go. Two
limits apply: it only runs on the user's explicit choice of this option
for one upload, and runs of eight or more digits (card numbers, account
numbers, reference numbers, masked or not) are replaced with a marker
before sending -- an amount never has eight digits in a row.

Configuration is the commentary module's: GEMINI_API_KEY and GEMINI_MODEL
from .env (documented in docs/CONVENTIONS.md). A missing key is reported as
a distinct status (the frontend says which key to add), not an exception.
The call itself is one small function tests replace wholesale; nothing in
the suite reaches the network.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime

import httpx

from parsers.base import ParsedStatement, Transaction, extract_all_text
from storage.commentary import API_KEY_ENV, DEFAULT_MODEL, MODEL_ENV

_TIMEOUT_SECONDS = 60.0
_LONG_DIGIT_RUN_RE = re.compile(r"[\dXx*]{8,}")
_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")


class LLMNotConfiguredError(Exception):
    """GEMINI_API_KEY is not set. A config problem, not a transient failure."""


class LLMParseError(Exception):
    """The model call failed, or its reply was not a usable statement."""


def redact(text: str) -> str:
    return _LONG_DIGIT_RUN_RE.sub("[number]", text)


def _prompt(text: str) -> str:
    return (
        "The text below was extracted from one credit card statement PDF. "
        "Read it and return ONLY a JSON object with exactly this shape:\n"
        "{\n"
        '  "period_start": "YYYY-MM-DD",\n'
        '  "period_end": "YYYY-MM-DD",\n'
        '  "transactions": [\n'
        '    {"date": "YYYY-MM-DD", "description": "...", "amount": 123.45, '
        '"type": "debit" or "credit", "is_payment": true or false}\n'
        "  ],\n"
        '  "summary": {"purchases_total": 123.45 or null, "payments_credits_total": 123.45 or null}\n'
        "}\n"
        "Rules: one entry per transaction line, in statement order; amount is a positive "
        "number; type is credit for money coming back to the cardholder (payments, refunds, "
        "reversals, cashback) and debit for everything else; is_payment is true only for a "
        "credit that is the cardholder paying the card bill, never for a refund. summary "
        "holds the statement's own printed totals for purchases/debits and for "
        "payments/credits, or null where the statement does not print one. Do not invent "
        "rows. No prose, no markdown fences.\n\n"
        + text
    )


def _call_gemini(api_key: str, text: str) -> str:
    """POST the prompt to Gemini and return the reply text. Any HTTP error,
    timeout, or unexpected response shape raises; the caller treats every
    failure alike."""
    model = os.environ.get(MODEL_ENV) or DEFAULT_MODEL
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {
        "contents": [{"parts": [{"text": _prompt(text)}]}],
        "generationConfig": {"responseMimeType": "application/json"},
    }
    response = httpx.post(url, params={"key": api_key}, json=body, timeout=_TIMEOUT_SECONDS)
    response.raise_for_status()
    data = response.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as e:
        raise ValueError(f"unexpected Gemini response shape: {e!r}")


def _date(value, field: str) -> date:
    if not isinstance(value, str):
        raise LLMParseError(f"{field}: expected a YYYY-MM-DD string")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise LLMParseError(f"{field}: not a valid YYYY-MM-DD date")


def _amount(value, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LLMParseError(f"{field}: expected a number")
    if value < 0:
        raise LLMParseError(f"{field}: amounts must be positive")
    return float(value)


def _optional_amount(value, field: str) -> "float | None":
    return None if value is None else _amount(value, field)


def _transaction(raw, index: int) -> Transaction:
    field = f"transactions[{index}]"
    if not isinstance(raw, dict):
        raise LLMParseError(f"{field}: expected an object")
    description = raw.get("description")
    if not isinstance(description, str) or not description.strip():
        raise LLMParseError(f"{field}.description: expected non-empty text")
    txn_type = raw.get("type")
    if txn_type not in ("debit", "credit"):
        raise LLMParseError(f"{field}.type: expected debit or credit")
    txn_date = _date(raw.get("date"), f"{field}.date")
    return Transaction(
        date=datetime(txn_date.year, txn_date.month, txn_date.day),
        description=description.strip(),
        amount=_amount(raw.get("amount"), f"{field}.amount"),
        type=txn_type,
        reward_points=None,
        # A debit is never a payment whatever the model says (parsers.base rule).
        is_payment=txn_type == "credit" and bool(raw.get("is_payment", False)),
    )


def parse_reply(reply: str) -> "tuple[ParsedStatement, dict]":
    """The model's text -> (ParsedStatement, summary), or LLMParseError."""
    try:
        data = json.loads(_FENCE_RE.sub("", reply or ""))
    except (json.JSONDecodeError, TypeError) as e:
        raise LLMParseError(f"reply is not JSON: {e}")
    if not isinstance(data, dict):
        raise LLMParseError("reply is not a JSON object")
    rows = data.get("transactions")
    if not isinstance(rows, list):
        raise LLMParseError("transactions: expected a list")
    parsed = ParsedStatement(
        period_start=_date(data.get("period_start"), "period_start"),
        period_end=_date(data.get("period_end"), "period_end"),
        transactions=[_transaction(raw, i) for i, raw in enumerate(rows)],
    )
    raw_summary = data.get("summary") or {}
    if not isinstance(raw_summary, dict):
        raise LLMParseError("summary: expected an object")
    summary = {
        "purchases_total": _optional_amount(raw_summary.get("purchases_total"), "summary.purchases_total"),
        "payments_credits_total": _optional_amount(
            raw_summary.get("payments_credits_total"), "summary.payments_credits_total"
        ),
    }
    return parsed, summary


def parse_with_summary(pdf_path: str, password: "str | None") -> "tuple[ParsedStatement, dict]":
    """One model call for this one file: the statement and its printed totals."""
    api_key = os.environ.get(API_KEY_ENV)
    if not api_key:
        raise LLMNotConfiguredError(f"{API_KEY_ENV} is not set in .env")

    text = redact("\n".join(extract_all_text(pdf_path, password)))
    try:
        reply = _call_gemini(api_key, text)
    except Exception as e:  # any failure -- HTTP, timeout, shape -- alike
        raise LLMParseError(f"model call failed: {type(e).__name__}") from e
    return parse_reply(reply)
