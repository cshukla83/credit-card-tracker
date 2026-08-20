"""Import a card statement PDF into the tracker DB.

Run from the project root, with the venv active:
    python -m scripts.import_statement <pdf_path> --card-id <int>

Example:
    python -m scripts.import_statement data/statements/hdfc_sample.pdf --card-id 1
"""

import argparse
import os
import sys

from dotenv import load_dotenv

import parsers.hdfc as hdfc_dispatch
from storage.adapters import from_hdfc
from storage.cards import get_card
from storage.db import get_connection, init_db
from storage.writes import insert_statement

load_dotenv()

# TODO: generalize this once a second bank is added. Only HDFC exists right
# now, so a real per-bank config/lookup mechanism would be speculative -- a
# single hardcoded entry is honest about the current scope.
_BANK_PASSWORD_ENV_KEYS = {
    "HDFC": "HDFC_SAMPLE_PASSWORD",
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

        password_env_key = _BANK_PASSWORD_ENV_KEYS.get(card["bank"])
        if password_env_key is None:
            print(f"Error: no password lookup configured for bank {card['bank']!r}")
            sys.exit(1)

        password = os.environ.get(password_env_key)
        if not password:
            print(f"Error: {password_env_key} not set in .env")
            sys.exit(1)

        parsed = hdfc_dispatch.parse(args.pdf_path, password, card_type=card["card_type"])
        insert_args = from_hdfc(parsed, card_id=args.card_id)
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
