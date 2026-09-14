"""The web upload path (Sessions 97-98): a new entry point onto the CLI's
import pipeline, not a parallel one.

Step 1, detection (`detect()`): read the PDF's first page
(parsers.detect.unlock), identify the bank (parsers.detect.identify), then
resolve that (bank, card_type) against the cards table (`resolve_card`).
Everything the endpoint returns is a plain dict with a "status" key so the
frontend branches on one field:

  matched        exactly one card of that bank/card type
  zero_match     none -- the frontend offers to create one (POST /cards)
  multi_match    several -- the frontend asks which, showing each card's
                 nickname and last statement period
  unrecognized   no bank landmark (or more than one) on page 1
  password_needed the file is encrypted and no .env password opens it.
                 Detection cannot name the bank here -- nothing was
                 readable -- so bank/card_type are null and the .env keys
                 that were tried are listed instead.

Step 2, preview (`preview()`): with a card resolved, run the CLI's own
pipeline -- the registry's parse() for the card's bank -- then check for a
duplicate (same card, same period: the key insert_statement() dedups on),
reconcile the parsed sums against the statement's summary box, and hold
the parsed statement in memory under an opaque upload_id. Nothing is
written. Step 3, confirm (`confirm()`): write the held statement through
insert_statement(), the same atomic call the CLI makes, unless
reconciliation failed and the caller did not explicitly override.

The preview cache is a module-level dict: this is a single-user app run as
one process, so an in-process dict is the whole story -- no expiry, no
persistence, no cross-worker sharing. A server restart empties it, and
confirm() reports that as "preview expired" rather than crashing.
"""

from __future__ import annotations

import sqlite3
import uuid
from typing import NamedTuple

from parsers.detect import PasswordNeededError, identify, unlock
from parsers.reconcile import reconcile
from parsers.registry import BANKS
from storage.adapters import from_parsed_statement
from storage.cards import find_cards_for_type, get_card
from storage.dates import to_date_str
from storage.reads import find_statement
from storage.writes import insert_statement


class CardNotFoundError(Exception):
    pass


class UnsupportedCardError(Exception):
    """The card's bank has no registry entry, or its card_type no parser."""


class StatementPeriodError(Exception):
    """The parser could not read the statement period, so the statement
    cannot be identified (or deduplicated) -- it is not importable."""


class PreviewExpiredError(Exception):
    pass


class ReconciliationBlockedError(Exception):
    pass


class DuplicateStatementError(Exception):
    pass


class PendingUpload(NamedTuple):
    card_id: int
    parsed: dict
    reconciliation: dict


PREVIEWS: "dict[str, PendingUpload]" = {}


def resolve_card(conn: sqlite3.Connection, bank: str, card_type: str) -> dict:
    """matched / zero_match / multi_match for one detected (bank, card_type)."""
    cards = find_cards_for_type(conn, bank, card_type)
    if len(cards) == 1:
        return {
            "status": "matched",
            "card_id": cards[0]["card_id"],
            "bank": bank,
            "card_type": card_type,
        }
    if not cards:
        return {"status": "zero_match", "bank": bank, "card_type": card_type}
    return {"status": "multi_match", "bank": bank, "card_type": card_type, "candidates": cards}


def detect(conn: sqlite3.Connection, pdf_path: str) -> dict:
    try:
        unlocked = unlock(pdf_path)
    except PasswordNeededError as e:
        return {
            "status": "password_needed",
            "bank": None,
            "card_type": None,
            "tried_env_keys": e.tried_env_keys,
        }
    identified = identify(unlocked.first_page_text)
    if identified is None:
        return {"status": "unrecognized"}
    bank, card_type = identified
    return resolve_card(conn, bank, card_type)


def _bank_for(card: dict):
    bank = BANKS.get(card["bank"])
    if bank is None:
        raise UnsupportedCardError(
            f"No parser configured for bank {card['bank']!r} "
            f"(known banks: {', '.join(sorted(BANKS))})"
        )
    return bank


def preview(conn: sqlite3.Connection, pdf_path: str, card_id: int) -> dict:
    card = get_card(conn, card_id)
    if card is None:
        raise CardNotFoundError(f"No such card: {card_id}")
    bank = _bank_for(card)

    unlocked = unlock(pdf_path)
    try:
        parsed = bank.parse(pdf_path, unlocked.password, card_type=card["card_type"])
        summary = bank.extract_summary(pdf_path, unlocked.password, card_type=card["card_type"])
    except NotImplementedError as e:
        raise UnsupportedCardError(str(e)) from e

    period_start, period_end = parsed["period_start"], parsed["period_end"]
    if period_start is None or period_end is None:
        raise StatementPeriodError("Could not read the statement period from this PDF")

    existing = find_statement(conn, card_id, period_start, period_end)
    if existing is not None:
        return {
            "status": "duplicate",
            "card_id": card_id,
            "statement_id": existing["id"],
            "period_start": to_date_str(period_start),
            "period_end": to_date_str(period_end),
        }

    reconciliation = reconcile(
        parsed["transactions"],
        summary.get(bank.summary_debit_key),
        summary.get(bank.summary_credit_key),
    )
    upload_id = uuid.uuid4().hex
    PREVIEWS[upload_id] = PendingUpload(card_id=card_id, parsed=parsed, reconciliation=reconciliation)
    return {
        "status": "preview",
        "upload_id": upload_id,
        "card_id": card_id,
        "period_start": to_date_str(period_start),
        "period_end": to_date_str(period_end),
        "transaction_count": len(parsed["transactions"]),
        "reconciliation": reconciliation,
    }


def confirm(conn: sqlite3.Connection, upload_id: str, override_reconciliation: bool) -> dict:
    pending = PREVIEWS.get(upload_id)
    if pending is None:
        raise PreviewExpiredError("Preview expired or already imported -- upload the file again")
    if pending.reconciliation["status"] != "match" and not override_reconciliation:
        raise ReconciliationBlockedError(
            "Parsed totals do not match the statement summary; "
            "set override_reconciliation to import anyway"
        )

    statement_id = insert_statement(conn, *from_parsed_statement(pending.parsed, card_id=pending.card_id))
    if statement_id is None:
        # The preview ran the duplicate check, so this only happens if the
        # same statement was imported between preview and confirm (say, by
        # the CLI). Drop the stale preview: it can never be confirmed.
        PREVIEWS.pop(upload_id, None)
        raise DuplicateStatementError("This statement was already imported for this card")

    PREVIEWS.pop(upload_id, None)
    return {"statement_id": statement_id, "transaction_count": len(pending.parsed["transactions"])}
