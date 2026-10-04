# Security & Privacy

## Everything runs locally

This application runs entirely on your machine. There is no hosted backend,
no cloud database, no telemetry. Your transaction data lives in a local
SQLite file (`data/tracker.db` by default) and never leaves your computer
— with one exception described below.

## The AI-assist exception

When you enable the **LLM-assist toggle** for a statement upload (used for
banks without a dedicated parser), the application sends the statement's
extracted text to the Google Gemini API for parsing. Similarly, the
**analytics dashboard commentary** feature sends category, subcategory and
merchant names with their amounts for the chosen period to Gemini for a
natural-language summary.

**What is sent:**
- Transaction descriptions, dates, and amounts
- Category, subcategory and merchant names with amounts, plus period totals (commentary)

**What is never sent:**
- Card numbers or account numbers (stripped before the API call)
- PDF files or raw binary data
- Statement passwords
- Your database
- Raw transaction descriptions or dates in the commentary request

Both features require a `GEMINI_API_KEY` in your `.env` file and do nothing
without one. If you prefer fully offline operation, leave the key unset —
the dedicated parsers (HDFC, ICICI, SBI, IndusInd) work entirely locally.

## Sensitive files

| File | Contains | Protected by |
|------|----------|-------------|
| `.env` | Bank statement PDF passwords, Gemini API key | `.gitignore` — never committed |
| `data/tracker.db` | All parsed transactions and card records | `.gitignore` — never committed |
| `data/statements/*.pdf` | Original bank statement PDFs | `.gitignore` (`*.pdf`) — never committed |

**Your responsibility:**
- Keep your `.env` file private. Do not share it or commit it to any repository.
- Back up `data/tracker.db` if you value the data — it is your only copy.
- Statement PDFs in `data/statements/` are your originals. The app reads
  them during import but does not modify them.

## Statement passwords

Bank statement PDF passwords are read from environment variables at parse
time (`HDFC_SAMPLE_PASSWORD`, `ICICI_SAMPLE_PASSWORD`, etc.). They are:

- Never written to the database
- Never included in API responses
- Never logged or printed to stdout
- Never sent to any external service

## Reporting a vulnerability

If you find a security issue, please open a GitHub issue or email the
maintainer directly. This is a personal project — there is no bug bounty,
but responsible reports are appreciated.
