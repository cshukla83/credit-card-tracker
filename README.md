# Credit Card Statement Tracker

A local-first web application that parses Indian bank credit card statement
PDFs, extracts transactions, and gives you a searchable, categorised view of
your spending — with an analytics dashboard and optional AI-assisted parsing
for unsupported banks.

Built with Python, FastAPI, and SQLite. Everything runs on your machine;
your data never leaves it (see [SECURITY.md](SECURITY.md) for the one
optional exception).

## Supported Banks

| Bank | Card Types | Parser |
|------|-----------|--------|
| HDFC | Diners (current + legacy format) | Dedicated |
| ICICI | Coral | Dedicated |
| SBI | SimplyClick / Titan | Dedicated |
| IndusInd | Legend | Dedicated |
| Any other bank | — | AI-assisted (Google Gemini) or best-effort heuristic |

## Features

- **Upload & parse** — drop a PDF (passwords are read from `.env`), preview
  extracted transactions before importing
- **Auto-categorisation** — learns from your manual category assignments and
  applies them to future transactions by merchant match; bulk-accept
  suggestions for selected transactions
- **Totals check** — each upload is reconciled against the statement's printed
  totals (Match, Mismatch or Unverified) before you import
- **Analytics dashboard** — spend breakdown by category, subcategory, or
  merchant across configurable time periods
- **AI commentary** — optional natural-language spending summary powered by
  Gemini (on demand, via the Generate insight button)
- **CLI tools** — create cards, import statements, and query transactions
  from the command line

## Tech Stack

- **Backend:** Python 3.10+, FastAPI, Uvicorn
- **Database:** SQLite (single file, zero config)
- **PDF parsing:** pdfplumber
- **AI (optional):** Google Gemini API
- **Frontend:** Single-page HTML/JS (no build step)
- **Tests:** pytest (788 tests)

## Quick Start

```bash
# Clone and set up
git clone https://github.com/cshukla83/credit-card-tracker.git
cd credit-card-tracker
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env — add your bank statement PDF passwords
# Optionally add GEMINI_API_KEY for AI features

# Run
uvicorn main:app --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser.

## CLI Scripts

Run from the project root with the venv active. Always use `python -m`
(not `python scripts/foo.py`) so imports resolve correctly.

```bash
# Create a card
python -m scripts.create_card --bank HDFC --card-type Diners --nickname "Primary"

# Import a statement
python -m scripts.import_statement data/statements/hdfc_aug2026.pdf --card-id 1

# Query transactions
python -m scripts.query_transactions --card-id 1 --start 2026-08-01 --end 2026-08-31
```

## Running Tests

```bash
source venv/bin/activate
pytest
```

All 788 tests run without a database, API key, or statement files — they
use synthetic PDFs generated in the test fixtures.

## Project Structure

```
credit-card-tracker/
├── main.py                  # FastAPI app — all API endpoints
├── parsers/                 # Bank-specific + generic PDF parsers
│   ├── hdfc/                #   HDFC Diners (current + legacy)
│   ├── icici/               #   ICICI Coral
│   ├── sbi/                 #   SBI Titan
│   ├── indusind/            #   IndusInd Legend
│   ├── detect.py            #   Bank detection from PDF landmarks
│   ├── generic_fallback.py  #   Best-effort parser for unknown banks
│   ├── llm_assist.py        #   Gemini-powered parser (optional)
│   ├── reconcile.py         #   Parsed totals vs. statement summary
│   └── registry.py          #   Bank → parser routing
├── storage/                 # SQLite data layer
│   ├── db.py                #   Connection factory (reads DB_PATH)
│   ├── schema.py            #   Table definitions
│   ├── cards.py             #   Card CRUD
│   ├── reads.py             #   Transaction queries
│   ├── writes.py            #   Transaction writes
│   ├── upload.py            #   Web upload pipeline
│   ├── categories.py        #   Auto-categorisation engine
│   ├── aggregate.py         #   Dashboard aggregation
│   └── commentary.py        #   AI spending commentary
├── scripts/                 # CLI utilities
├── static/index.html        # Single-page frontend
├── tests/                   # 788 pytest tests
├── requirements.txt         # Python dependencies
├── pyproject.toml           # Project metadata + pytest config
├── .env.example             # Environment variable template
├── SECURITY.md              # Privacy & data handling
└── LICENSE                  # MIT
```

## Documentation

- [SECURITY.md](SECURITY.md) — what stays local, what the AI toggle sends,
  how passwords are handled
- [.env.example](.env.example) — all configuration options with comments

## License

[MIT](LICENSE)
