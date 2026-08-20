"""Create a card (bank + card type + optional nickname) in the tracker DB.

Run from the project root, with the venv active:
    python -m scripts.create_card --bank <str> --card-type <str> [--nickname <str>]

Example:
    python -m scripts.create_card --bank HDFC --card-type Diners --nickname Primary
"""

import argparse
import sys

from storage.cards import CardAlreadyExistsError, create_card
from storage.db import get_connection, init_db


def main():
    parser = argparse.ArgumentParser(description="Create a card in the tracker DB.")
    parser.add_argument("--bank", required=True)
    parser.add_argument("--card-type", required=True)
    parser.add_argument("--nickname", default=None)
    args = parser.parse_args()

    init_db()
    conn = get_connection()
    try:
        try:
            card_id = create_card(conn, args.bank, args.card_type, args.nickname)
        except CardAlreadyExistsError:
            print(
                f"Error: card already exists (bank={args.bank}, "
                f"card_type={args.card_type}, nickname={args.nickname})",
                file=sys.stderr,
            )
            sys.exit(1)

        print(
            f"Created card id={card_id} (bank={args.bank}, "
            f"card_type={args.card_type}, nickname={args.nickname})"
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
