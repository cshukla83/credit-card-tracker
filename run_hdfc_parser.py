import argparse
import os

from dotenv import load_dotenv

import parsers.hdfc as hdfc_dispatch
from parsers.hdfc_diners import extract_summary

load_dotenv()

DEFAULT_PDF_PATH = "data/statements/hdfc_sample.pdf"
PASSWORD = os.environ["HDFC_SAMPLE_PASSWORD"]
# Only the Diners parser exists so far; hardcoded rather than exposed as a
# flag until a second card_type is actually implemented.
CARD_TYPE = "Diners"


def _reconciles(actual, expected, tolerance=0.01):
    if expected is None:
        return None
    return abs(actual - expected) < tolerance


def _yes_no(value):
    if value is None:
        return "unknown (summary total not found)"
    return "yes" if value else "no"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf_path", nargs="?", default=DEFAULT_PDF_PATH)
    args = parser.parse_args()

    transactions = hdfc_dispatch.parse(args.pdf_path, PASSWORD, card_type=CARD_TYPE)
    summary = extract_summary(args.pdf_path, PASSWORD)

    debits = [t for t in transactions if t["type"] == "debit"]
    credits = [t for t in transactions if t["type"] == "credit"]

    debit_total = sum(t["amount"] for t in debits)
    credit_total = sum(t["amount"] for t in credits)

    debit_match = _reconciles(debit_total, summary["purchases_debit"])
    credit_match = _reconciles(credit_total, summary["payments_credits_received"])

    print(f"Transactions parsed: {len(transactions)} ({len(debits)} debit, {len(credits)} credit)")
    print(f"Debit total reconciles with statement summary: {_yes_no(debit_match)}")
    print(f"Credit total reconciles with statement summary: {_yes_no(credit_match)}")


if __name__ == "__main__":
    main()
