import argparse
import sys
from datetime import date

from storage.db import get_connection, init_db
from storage.reads import get_transactions

_DESCRIPTION_WIDTH = 60


def _truncate(text: str, width: int = _DESCRIPTION_WIDTH) -> str:
    if len(text) <= width:
        return text
    return text[: width - 1] + "…"


def _print_table(rows):
    print(f"{'date':<10} {'amount':>10} {'type':<8} description")
    for row in rows:
        print(
            f"{row['txn_date']:<10} {row['amount']:>10.2f} "
            f"{row['txn_type']:<8} {_truncate(row['description'])}"
        )


def main():
    parser = argparse.ArgumentParser(description="Query transactions from the tracker DB.")
    parser.add_argument("--card-id", type=int, default=None)
    parser.add_argument("--start", type=date.fromisoformat, default=None, metavar="YYYY-MM-DD")
    parser.add_argument("--end", type=date.fromisoformat, default=None, metavar="YYYY-MM-DD")
    args = parser.parse_args()

    if args.start is not None and args.end is not None and args.start > args.end:
        print(f"Error: --start ({args.start}) is after --end ({args.end})")
        sys.exit(1)

    init_db()
    conn = get_connection()
    try:
        rows = get_transactions(conn, card_id=args.card_id, start_date=args.start, end_date=args.end)
    finally:
        conn.close()

    if not rows:
        print("No transactions found.")
        return

    _print_table(rows)
    print(f"{len(rows)} transactions")


if __name__ == "__main__":
    main()
