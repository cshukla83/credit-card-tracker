"""Import a card statement PDF into the tracker DB.

Run from the project root, with the venv active:
    python -m scripts.import_statement <pdf_path> --card-id <int>

Example:
    python -m scripts.import_statement data/statements/hdfc_sample.pdf --card-id 1
"""

import argparse
import os
import sys
from typing import Callable, NamedTuple

from dotenv import load_dotenv

import parsers.hdfc as hdfc_dispatch
import parsers.icici as icici_dispatch
import parsers.sbi as sbi_dispatch
from storage.adapters import from_parsed_statement
from storage.cards import get_card
from storage.db import get_connection, init_db
from storage.writes import insert_statement

load_dotenv()


class _Bank(NamedTuple):
    """Everything bank-specific about importing a statement, in one place."""

    password_env_key: str
    # The bank's dispatch package (parsers/<bank>/__init__.py), not a
    # card-type-specific parser: card_type routing happens inside it.
    parse: Callable[..., dict]


# Bank name (as stored in cards.bank) -> its import config. Generalized in
# Session 30 against two real banks: what used to be a one-entry
# _BANK_PASSWORD_ENV_KEYS dict plus a hardcoded parsers.hdfc call is now a
# single registry, so adding a third bank is one entry here rather than edits
# scattered across this module.
_BANKS = {
    "HDFC": _Bank(password_env_key="HDFC_SAMPLE_PASSWORD", parse=hdfc_dispatch.parse),
    "ICICI": _Bank(password_env_key="ICICI_SAMPLE_PASSWORD", parse=icici_dispatch.parse),
    "SBI": _Bank(password_env_key="SBI_SAMPLE_PASSWORD", parse=sbi_dispatch.parse),
}


def main():
    parser = argparse.ArgumentParser(description="Import a card statement PDF into the tracker DB.")
    parser.add_argument("pdf_path")
    parser.add_argument("--card-id", type=int, required=True)
    args = parser.parse_args()

    init_db()
    conn = get_connection()
    try:
        card = get_card(conn, args.card_id)
        if card is None:
            print(f"Error: card_id {args.card_id} not found")
            sys.exit(1)

        bank = _BANKS.get(card["bank"])
        if bank is None:
            print(
                f"Error: no parser configured for bank {card['bank']!r} "
                f"(known banks: {', '.join(sorted(_BANKS))})"
            )
            sys.exit(1)

        password = os.environ.get(bank.password_env_key)
        if not password:
            print(f"Error: {bank.password_env_key} not set in .env")
            sys.exit(1)

        parsed = bank.parse(args.pdf_path, password, card_type=card["card_type"])
        insert_args = from_parsed_statement(parsed, card_id=args.card_id)
        statement_id = insert_statement(conn, *insert_args)

        if statement_id is None:
            print(
                f"Skipped: already imported (card_id={args.card_id}, "
                f"period={parsed['period_start']}..{parsed['period_end']})"
            )
            return

        print(
            f"Imported {len(parsed['transactions'])} transactions "
            f"(statement_id={statement_id}, card_id={args.card_id})"
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
