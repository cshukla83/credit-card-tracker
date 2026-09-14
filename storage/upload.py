"""The web upload path (Sessions 97-112): a new entry point onto the CLI's
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
pipeline -- the registry's parse() for the card's bank, or for a format no
landmark recognised either the bank-agnostic parsers.generic_fallback
(strategy="best_effort", Session 99) or the model-backed
parsers.llm_assist (strategy="llm_assist", Session 100) -- then check for a
duplicate (same card, same period: the key insert_statement() dedups on),
reconcile the parsed sums against the statement's summary box, and hold
the parsed statement in memory under an opaque upload_id. Nothing is
written. Step 3, confirm (`confirm()`): write the held statement through
insert_statement(), the same atomic call the CLI makes, unless
reconciliation failed and the caller did not explicitly override.

A card can be pending rather than existing (Session 112): preview takes
either an existing card_id or the details of a card to create -- bank,
card_type, nickname -- and holds them with the parsed statement; confirm
then creates the card and writes the statement as one atomic unit
(storage.writes.insert_statement_with_new_card). Until Session 112 the
zero-match form created the card immediately, before preview, and a
preview that was never confirmed left an orphan card behind. A pending
card skips the duplicate check: it has no statements to collide with.

The preview cache is a module-level dict: this is a single-user app run as
one process, so an in-process dict is the whole story -- no expiry, no
persistence, no cross-worker sharing. A server restart empties it, and
confirm() reports that as "preview expired" rather than crashing.
"""

from __future__ import annotations

import sqlite3
import uuid
from typing import Callable, NamedTuple

from parsers import generic_fallback, llm_assist
from parsers.detect import PasswordNeededError, identify, unlock
from parsers.reconcile import reconcile
from parsers.registry import BANKS
from storage.adapters import from_parsed_statement
from storage.cards import find_cards_for_type, get_card
from storage.categories import suggest_categories_for_descriptions
from storage.dates import to_date_str
from storage.reads import find_statement
from storage.writes import insert_statement, insert_statement_with_new_card


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


class UnknownStrategyError(Exception):
    pass


class Strategy(NamedTuple):
    """How a preview parses: one call that yields the ParsedStatement and the
    statement's summary figures together, plus which two summary keys the
    debit and credit sums reconcile against. A registry bank composes its
    parse() and extract_summary(); the LLM path is a single model call that
    returns both -- which is why this is one callable, not two."""

    run: "Callable[[str, str | None], tuple[dict, dict]]"
    summary_debit_key: str
    summary_credit_key: str


STRATEGIES = ("detected", "best_effort", "llm_assist")


class CardChoiceError(Exception):
    """Neither, or both, of card_id and a new card's details were given."""


class PendingUpload(NamedTuple):
    card_id: "int | None"      # an existing card ...
    new_card: "dict | None"    # ... or {bank, card_type, nickname} to create on confirm
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


def _strategy_for(card: dict, strategy: str) -> Strategy:
    if strategy == "best_effort":
        # Bank-agnostic by definition: the card's bank need not be in the
        # registry (that is the point -- an unrecognised format).
        return Strategy(
            run=lambda path, password: (
                generic_fallback.parse(path, password),
                generic_fallback.extract_summary(path, password),
            ),
            summary_debit_key="purchases",
            summary_credit_key="payments_credits",
        )
    if strategy == "llm_assist":
        return Strategy(
            run=llm_assist.parse_with_summary,
            summary_debit_key="purchases_total",
            summary_credit_key="payments_credits_total",
        )
    if strategy == "detected":
        bank = _bank_for(card)
        card_type = card["card_type"]
        return Strategy(
            run=lambda path, password: (
                bank.parse(path, password, card_type=card_type),
                bank.extract_summary(path, password, card_type=card_type),
            ),
            summary_debit_key=bank.summary_debit_key,
            summary_credit_key=bank.summary_credit_key,
        )
    raise UnknownStrategyError(
        f"Unknown strategy {strategy!r} (expected one of: {', '.join(STRATEGIES)})"
    )


def _password_needed(card: dict, error: PasswordNeededError) -> dict:
    # Unlike detect(), preview knows the card, so the bank is named and --
    # when the bank is a known one -- so is the .env key to set. The two
    # ways to get here look the same from outside: no key in .env, or a key
    # that is set but does not open this file. Neither gets a partial parse.
    bank = BANKS.get(card["bank"])
    return {
        "status": "password_needed",
        "bank": card["bank"],
        "card_type": card["card_type"],
        "password_env_key": bank.password_env_key if bank else None,
        "tried_env_keys": error.tried_env_keys,
    }


def _card_for(conn: sqlite3.Connection, card_id: "int | None", new_card: "dict | None") -> dict:
    """The card a preview is for, as a dict with bank / card_type / id --
    from the cards table for an existing card_id, or from the payload for a
    pending one (id None). Exactly one of the two must be given."""
    if (card_id is None) == (new_card is None):
        raise CardChoiceError("Give exactly one of card_id or a new card (bank and card_type)")
    if card_id is not None:
        card = get_card(conn, card_id)
        if card is None:
            raise CardNotFoundError(f"No such card: {card_id}")
        return card
    bank = (new_card.get("bank") or "").strip()
    card_type = (new_card.get("card_type") or "").strip()
    nickname = (new_card.get("nickname") or "").strip() or None
    if not bank or not card_type:
        raise CardChoiceError("A new card needs both bank and card_type")
    return {"id": None, "bank": bank, "card_type": card_type, "nickname": nickname}


def preview(
    conn: sqlite3.Connection,
    pdf_path: str,
    card_id: "int | None" = None,
    strategy: str = "detected",
    new_card: "dict | None" = None,
) -> dict:
    card = _card_for(conn, card_id, new_card)
    pending_card = (
        None
        if card["id"] is not None
        else {"bank": card["bank"], "card_type": card["card_type"], "nickname": card["nickname"]}
    )
    chosen = _strategy_for(card, strategy)

    try:
        unlocked = unlock(pdf_path)
    except PasswordNeededError as e:
        return _password_needed(card, e)
    try:
        parsed, summary = chosen.run(pdf_path, unlocked.password)
    except NotImplementedError as e:
        raise UnsupportedCardError(str(e)) from e
    except llm_assist.LLMNotConfiguredError:
        # Expected on first use: the key is added by hand to .env. A status
        # the frontend can show, like password_needed, not an error.
        return {"status": "llm_not_configured", "api_key_env": llm_assist.API_KEY_ENV}
    except llm_assist.LLMParseError as e:
        # The call failed or the reply was unusable; nothing was written and
        # nothing is cached. The frontend offers the other strategy.
        return {"status": "llm_failed", "reason": str(e)}

    period_start, period_end = parsed["period_start"], parsed["period_end"]
    if period_start is None or period_end is None:
        raise StatementPeriodError("Could not read the statement period from this PDF")

    # A pending card has no statements yet, so nothing to collide with.
    existing = None if pending_card else find_statement(conn, card["id"], period_start, period_end)
    if existing is not None:
        return {
            "status": "duplicate",
            "card_id": card["id"],
            "statement_id": existing["id"],
            "period_start": to_date_str(period_start),
            "period_end": to_date_str(period_end),
        }

    reconciliation = reconcile(
        parsed["transactions"],
        summary.get(chosen.summary_debit_key),
        summary.get(chosen.summary_credit_key),
    )
    upload_id = uuid.uuid4().hex
    PREVIEWS[upload_id] = PendingUpload(
        card_id=card["id"], new_card=pending_card, parsed=parsed, reconciliation=reconciliation
    )
    return {
        "status": "preview",
        "upload_id": upload_id,
        "card_id": card["id"],
        "new_card": pending_card,
        "strategy": strategy,
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

    if pending.new_card is not None:
        # Card and statement in one transaction (Session 112). A nickname
        # collision (CardAlreadyExistsError) or a bad row leaves nothing
        # behind and the preview stays held, so the user can change the
        # details and confirm again.
        new = pending.new_card
        _, _, _, rows = from_parsed_statement(pending.parsed, card_id=0)
        card_id, statement_id = insert_statement_with_new_card(
            conn, new["bank"], new["card_type"], new["nickname"],
            pending.parsed["period_start"], pending.parsed["period_end"], rows,
        )
    else:
        card_id = pending.card_id
        statement_id = insert_statement(conn, *from_parsed_statement(pending.parsed, card_id=card_id))
        if statement_id is None:
            # The preview ran the duplicate check, so this only happens if
            # the same statement was imported between preview and confirm
            # (say, by the CLI). Drop the stale preview: it can never be
            # confirmed.
            PREVIEWS.pop(upload_id, None)
            raise DuplicateStatementError("This statement was already imported for this card")

    PREVIEWS.pop(upload_id, None)
    return {
        "statement_id": statement_id,
        "card_id": card_id,
        "transaction_count": len(pending.parsed["transactions"]),
    }


# --- preview detail (Session 103) --------------------------------------------

SAMPLE_ROWS = 5
NO_SUGGESTION = "(no suggestion)"


def _sample_row(txn: dict) -> dict:
    txn_date = txn["date"]
    return {
        "date": to_date_str(txn_date.date() if hasattr(txn_date, "date") else txn_date),
        "description": txn["description"],
        "amount": txn["amount"],
        "type": txn["type"],
    }


def preview_detail(conn: sqlite3.Connection, upload_id: str) -> dict:
    """A closer look at a held preview: the first and last few parsed rows,
    and what the category engine would suggest for every row -- suggested,
    not assigned. Reads the same cache confirm() reads; writes nothing.

    The samples are slices of the parsed list as-is: a statement of ten
    rows or fewer has start and end overlapping or covering everything,
    and the frontend draws its gap marker only when total_rows exceeds
    the two samples combined. The breakdown runs over every parsed row,
    not just the samples, with rows the engine has no suggestion for
    counted under NO_SUGGESTION so the counts always sum to total_rows.
    """
    pending = PREVIEWS.get(upload_id)
    if pending is None:
        raise PreviewExpiredError("Preview expired or already imported -- upload the file again")

    transactions = pending.parsed["transactions"]
    suggestions = suggest_categories_for_descriptions(
        conn, [t["description"] for t in transactions]
    )
    counts: "dict[str, int]" = {}
    for suggestion in suggestions:
        key = suggestion["value"] if suggestion["value"] is not None else NO_SUGGESTION
        counts[key] = counts.get(key, 0) + 1
    breakdown = sorted(counts.items(), key=lambda item: (-item[1], item[0]))

    return {
        "upload_id": upload_id,
        "total_rows": len(transactions),
        "sample_start": [_sample_row(t) for t in transactions[:SAMPLE_ROWS]],
        "sample_end": [_sample_row(t) for t in transactions[-SAMPLE_ROWS:]] if transactions else [],
        "category_breakdown": [{"category": value, "count": count} for value, count in breakdown],
    }
