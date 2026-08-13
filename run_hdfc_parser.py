import os

from dotenv import load_dotenv

from parsers.hdfc import extract_summary, parse

load_dotenv()

PDF_PATH = "data/statements/hdfc_sample.pdf"
PASSWORD = os.environ["HDFC_SAMPLE_PASSWORD"]


def _reconciles(actual, expected, tolerance=0.01):
    if expected is None:
        return None
    return abs(actual - expected) < tolerance


def _yes_no(value):
    if value is None:
        return "unknown (summary total not found)"
    return "yes" if value else "no"


def main():
    transactions = parse(PDF_PATH, PASSWORD)
    summary = extract_summary(PDF_PATH, PASSWORD)

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
