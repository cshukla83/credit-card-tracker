"""The web upload path (Session 97): a new entry point onto the CLI's import
pipeline, not a parallel one.

Step 1, detection (this module's `detect()`): read the PDF's first page
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
"""

from __future__ import annotations

import sqlite3

from parsers.detect import PasswordNeededError, identify, unlock
from storage.cards import find_cards_for_type


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
