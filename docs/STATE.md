# Project State

Always-current snapshot of the credit card statement tracker. Read this
first — it's the fastest way to get oriented. For the full session-by-
session history, see docs/DEVLOG.md. For process rules, see
docs/CONVENTIONS.md.

## What this is

A personal credit card statement tracker, built session by session as a
deliberate, hands-on vehicle for learning Claude Code. It parses monthly
PDF credit card statements — HDFC today, with SBI, ICICI, IndusInd, and
Axis identified as future targets — persists parsed transactions to a
local SQLite database, and will eventually expose that data through a
queryable API and a web dashboard.

Right now, only HDFC (Diners card type) is actually implemented, across
two known statement layouts (a current template and an older "legacy"
one, auto-detected from the PDF's own text).

## Current state

As of Session 25 (100 tests passing, working tree clean), the HDFC Diners
pipeline works end-to-end against real sample statements: parsing (both
layouts), an adapter bridging parser output to storage, atomic deduped
writes, a filtered read path, and `GET /transactions` and `GET /cards`
FastAPI endpoints wrapping the read/card-listing paths. A single-page HTML
frontend (`static/index.html`, served at `GET /`) consumes both endpoints
via `fetch()`, rendering a transactions table with a card picker and
date-range filters, filter state synced to the URL. Three command-line
tools exist — `create_card`, `import_statement`, and
`query_transactions` — all following the same shape, each documented with
a usage docstring plus a README section.

## Locked architectural decisions

- One parser module per bank + card type (e.g. `parsers/hdfc_diners.py`),
  with a dispatch layer (`parsers/hdfc/__init__.py`) routing by
  `card_type`. Statement-layout detection (current vs. legacy) is a
  separate, lower-level concern inside the bank module, not part of
  dispatch — the two axes are kept independent on purpose.
- `DB_PATH` is read fresh on every `get_connection()` call, never cached
  — the invariant that keeps tests isolated via `monkeypatch.setenv`.
- Multi-row writes (a statement plus all its transactions) go through a
  single SQL transaction — no partial writes survive a failure.
- Card lookups by nickname use an explicit `IS NULL` check, since SQL's
  `= NULL` never matches. SQLite's NULL-distinct behavior for the
  `(bank, card_type, nickname)` UNIQUE constraint is preserved by
  design, not fixed — multiple unnamed cards of the same bank/type are
  allowed on purpose.
- Date values are explicitly converted to ISO strings (`to_date_str()`)
  before storage/query binding, rather than relying on `sqlite3`'s
  implicit (and now-deprecated) date adapters.
- Distinguishing a UNIQUE violation from a FOREIGN KEY violation in
  `sqlite3` requires branching on `e.sqlite_errorname`, since both raise
  the same exception class — documented inline in the code, not only
  here.
- Read-path queries that JOIN `transactions` and `statements` explicitly
  `SELECT transactions.*`, never a bare `*`, to avoid a column-name
  collision on `id`. The same rule applies to `cards`/`statements` JOINs
  (`SELECT DISTINCT cards.*`), for the same reason.
- Card-type auto-detection from PDF content is explicitly deferred —
  `--card-id` is always required, never inferred.
- Single-user is implicit throughout — no auth, no user table, one local
  SQLite file.
- `GET /cards` (Session 25) returns only cards with at least one
  statement, via `storage.cards.list_cards_with_statements()` — a
  separate function from `list_cards()`, which still returns every card
  and is left untouched for the CLI. The frontend page is a thin
  `fetch()`-based consumer of both `/transactions` and `/cards` — it
  never reaches into the database directly, and never exposes anything
  those two endpoints don't already return.
- The frontend's filter-triggered fetches to `/transactions` are tagged
  with an incrementing sequence number so an out-of-order network
  response (an older request resolving after a newer one) can't
  overwrite the table with stale data. Filter state round-trips through
  the URL via `history.replaceState` (never `pushState`), so filtered
  views are bookmarkable without spamming browser history.

## Open flags

- `_BANK_PASSWORD_ENV_KEYS` (in `scripts/import_statement.py`) and the
  `parsers/hdfc` dispatch layer's `card_type` routing are both
  single-entry structures, hardcoded for HDFC only. Real generalization
  is deferred until a second bank exists to generalize against.
- Card identity has two known, unfixed asymmetries: `storage.cards.
  create_card`'s bank/card_type matching is case-sensitive, but
  `parsers/hdfc`'s dispatch is case-insensitive; and cards with a `NULL`
  nickname can silently accumulate duplicates, since SQLite treats each
  `NULL` as distinct.
- Card identity convention clarified during Session 25 verification:
  `nickname` must identify the physical card (e.g. `Primary`), never a
  statement period — `statements.period_start`/`period_end` already
  carries the month. Future imports should attach to the existing card,
  not create a new one per month.
- Whether `GET /transactions` (and now `GET /cards`) needs response
  pagination or a result-count cap is an open question — no evidence yet
  that it's a real problem.
- A `StarletteDeprecationWarning` (`httpx` with `starlette.testclient`)
  surfaced during Session 23's test run — unresolved, low-priority.

## Next arc

The current arc, set on 2026-08-20, is "HDFC UI end-to-end": Session 23
added the `/transactions` API endpoint, Session 24 added a minimal HTML
page consuming it (client-side `fetch()`, no server-rendered templating),
and Session 25 (done) added a card picker and date-range filters to that
page, backed by a new `/cards` endpoint. Session 26 onward is
deliberately left open, to be decided from what Sessions 23–25 actually
reveal is needed, not speculated now. Once the HDFC UI ships, the arc
moves to a second real bank (ICICI) — which is also when the deferred
password-key and dispatch-routing generalizations above finally happen,
against two real cases rather than speculatively.

## How this project works

See docs/CONVENTIONS.md for the full session methodology, DEVLOG entry
structure, learning summary format, data handling rules, and CLI
invocation convention. In short: scope is locked before code, Claude
Code builds, Chandra verifies in a separate terminal, and every session
ends in one commit covering code and docs together.
