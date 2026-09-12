"""LLM commentary for the analytics dashboard (Session 68).

The one place in the project where data leaves the machine, and it is
narrow by construction: `narrow_payload()` is the only thing that reaches
the model call, and it carries category names, category amounts, the
resolved period, and the total -- never subcategories, never any
transaction-level field. A test pins that.

Flow, given an already-computed aggregate for a resolved period:
  key missing            -> CommentaryNotConfiguredError (a config problem,
                            surfaced as such; the cache is NOT consulted)
  model call succeeds    -> upsert commentary_cache, return fresh
  model call fails (any) -> cached row for the same signature if there is
                            one, else CommentaryUnavailableError
"""

import json
import os
import sqlite3
from datetime import date

import httpx

API_KEY_ENV = "GEMINI_API_KEY"
MODEL_ENV = "GEMINI_MODEL"
DEFAULT_MODEL = "gemini-1.5-flash"
_NO_FILTER = "-"  # fixed sentinel so "no filter" always signs the same way
_TIMEOUT_SECONDS = 20.0


class CommentaryNotConfiguredError(Exception):
    """The Gemini API key is not set. Not a transient failure."""


class CommentaryUnavailableError(Exception):
    """The model call failed and nothing is cached for this view."""

    def __init__(self, cause: str):
        self.cause = cause
        super().__init__(f"Commentary unavailable and nothing cached yet for this view ({cause})")


def query_signature(
    start_date: date,
    end_date: date,
    bank: "str | None" = None,
    card_id: "int | None" = None,
    card_type: "str | None" = None,
) -> str:
    """Stable key for one *resolved* view.

    Built from the resolved dates -- so any granularity/mode combination
    that resolves to the same range shares one cache entry -- plus the
    filter values, each normalised: text stripped, an absent filter written
    as a fixed sentinel. Field order is fixed and the separator cannot
    appear in an ISO date or an int; bank / card_type are JSON-quoted so an
    exotic value cannot forge a boundary.
    """
    parts = [
        start_date.isoformat(),
        end_date.isoformat(),
        json.dumps(bank.strip()) if bank is not None and bank.strip() else _NO_FILTER,
        str(card_id) if card_id is not None else _NO_FILTER,
        json.dumps(card_type.strip()) if card_type is not None and card_type.strip() else _NO_FILTER,
    ]
    return "|".join(parts)


def narrow_payload(aggregate: dict) -> dict:
    """The ONLY data that goes to the model: period, total, and per-category
    name + amount. Built key by key from the aggregate rather than by
    copying it, so a new key on the aggregate shape (or a subcategories
    array, or anything transaction-level) can never ride along."""
    return {
        "period": {
            "start": aggregate["period"]["start"],
            "end": aggregate["period"]["end"],
        },
        "total": aggregate["total"],
        "categories": [
            {"category": c["category"], "amount": c["amount"]} for c in aggregate["categories"]
        ],
    }


def _prompt(payload: dict) -> str:
    return (
        "You are writing a short, plain-English note for a personal spending "
        "dashboard. Below are total card spend and spend by category for one "
        "period (amounts in INR; a negative amount means refunds exceeded "
        "spending in that category). Write 3 to 5 sentences: where most of the "
        "money went, anything notable, and one practical, non-judgemental "
        "observation. Do not invent transactions, merchants, or causes. Do not "
        "use bullet points or headings.\n\n"
        + json.dumps(payload, indent=2)
    )


def _call_gemini(api_key: str, payload: dict) -> str:
    """POST the narrowed payload to Gemini and return the commentary text.

    Kept as one small function so tests replace it wholesale; nothing in
    the suite ever reaches the network. Any HTTP error, timeout, or
    unexpected response shape raises -- callers treat every failure alike.
    Model is configurable via GEMINI_MODEL; the default has not been
    exercised against the live API from this codebase (Session 68 made no
    real calls), so a first live run should confirm it.
    """
    model = os.environ.get(MODEL_ENV) or DEFAULT_MODEL
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {"contents": [{"parts": [{"text": _prompt(payload)}]}]}
    response = httpx.post(
        url,
        params={"key": api_key},
        json=body,
        timeout=_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    data = response.json()
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as e:
        raise ValueError(f"unexpected Gemini response shape: {e!r}")
    text = (text or "").strip()
    if not text:
        raise ValueError("empty commentary from Gemini")
    return text


def get_cached(conn: sqlite3.Connection, signature: str) -> "dict | None":
    row = conn.execute(
        "SELECT commentary, generated_at FROM commentary_cache WHERE query_signature = ?",
        (signature,),
    ).fetchone()
    return {"commentary": row["commentary"], "generated_at": row["generated_at"]} if row else None


def upsert_cached(conn: sqlite3.Connection, signature: str, commentary: str) -> dict:
    """Replace (never accumulate) the commentary for a signature; returns the
    stored row so callers report the database's own generated_at."""
    with conn:
        conn.execute(
            "INSERT INTO commentary_cache (query_signature, commentary, generated_at) "
            "VALUES (?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(query_signature) DO UPDATE SET "
            "commentary = excluded.commentary, generated_at = CURRENT_TIMESTAMP",
            (signature, commentary),
        )
    return get_cached(conn, signature)


def generate_commentary(conn: sqlite3.Connection, aggregate: dict, signature: str) -> dict:
    """The flow described in the module docstring. Returns
    {"commentary", "generated_at", "cached": bool}."""
    api_key = os.environ.get(API_KEY_ENV)
    if not api_key:
        raise CommentaryNotConfiguredError("Gemini API key not configured")

    payload = narrow_payload(aggregate)
    try:
        text = _call_gemini(api_key, payload)
    except Exception as e:  # any failure -- rate limit, network, shape -- alike
        cached = get_cached(conn, signature)
        if cached:
            return {**cached, "cached": True}
        raise CommentaryUnavailableError(type(e).__name__)

    stored = upsert_cached(conn, signature, text)
    return {**stored, "cached": False}
