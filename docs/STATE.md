# Project State

Always-current snapshot of the credit card statement tracker. Read this
first — it's the fastest way to get oriented. For the full session-by-
session history, see docs/DEVLOG.md. For process rules, see
docs/CONVENTIONS.md.

## What this is

A personal credit card statement tracker, built session by session as a
deliberate, hands-on vehicle for learning Claude Code. It parses monthly
PDF credit card statements, persists parsed transactions to a local
SQLite database, and exposes that data through a queryable API and a
single-page web dashboard.

Four bank/card types are implemented and reconciling: HDFC Diners (across
two known statement layouts, a current template and an older "legacy"
one, auto-detected from the PDF's own text), ICICI Coral, SBI Titan, and
IndusInd Legend. Axis remains an identified future target, not yet
started.

## Current state

As of Session 35 (239 tests passing, working tree clean), the import
pipeline works end-to-end against real sample statements for four banks —
HDFC Diners (both layouts), ICICI Coral, SBI Titan, and IndusInd Legend —
and is bank-agnostic from the CLI down: parsing, an adapter bridging
parser output to storage (`from_parsed_statement`, shared by all four
banks), atomic deduped writes, a filtered read path, and
`GET /transactions`, `GET /cards`,
`GET /statement-months`, and `GET /card-types` FastAPI endpoints. The
`statements` table carries a `statement_month` column (e.g. `July-2026`),
generated from `period_end` rather than typed in. A single-page HTML
frontend (`static/index.html`, served at `GET /`) consumes all four
endpoints via `fetch()`, rendering a transactions table filterable by
card, bank/card type, statement month, and date range, with filter state
synced to the URL. Three command-line tools exist — `create_card`,
`import_statement`, and `query_transactions` — all following the same
shape, each documented with a usage docstring plus a README section.

All 18 real sample statements on disk — six HDFC, four ICICI, four SBI,
four IndusInd — parse and reconcile against each statement's own summary
totals, and every one of them is covered by a committed integration test.

## Locked architectural decisions

- One parser module per bank + card type (e.g. `parsers/hdfc_diners.py`),
  with a dispatch layer (`parsers/hdfc/__init__.py`) routing by
  `card_type`. Statement-layout detection (current vs. legacy) is a
  separate, lower-level concern inside the bank module, not part of
  dispatch — the two axes are kept independent on purpose.
- `DB_PATH` is read fresh on every `get_connection()` call, never cached
  — the invariant that keeps tests isolated via `monkeypatch.setenv`.
- `get_connection()` passes `check_same_thread=False` to `sqlite3.connect()`
  (Session 26, fixing a bug latent since Session 23). FastAPI's
  `Depends(get_db)` pattern can run a request's dependency setup, handler,
  and teardown on different threadpool threads, and `sqlite3`'s default
  `check_same_thread=True` crashes on that — including silently during
  teardown, after a correct response had already been sent. Safe to
  disable here specifically because every connection in this codebase is
  used *sequentially* by at most one thread at a time, never
  concurrently by more than one — the flag only guards against the
  concurrent case.
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
- Card-type auto-detection from PDF content is **not implemented** —
  `--card-id` is always required, never inferred. This remains an
  accurate description of current code behavior. The original decision to
  defer it has since been reversed on paper: auto-detection is a locked
  requirement of the expense categorization and analytics arc's
  upload/auto-import module. That reversal is decided but not yet built,
  and this line stands until it is.
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
- `statements.statement_month` (Session 26) is a `GENERATED ALWAYS AS
  (...) VIRTUAL` column, not `STORED` — empirically, SQLite's `ALTER
  TABLE ADD COLUMN` refuses to add a `STORED` generated column to a
  table that already has rows, which is true of every real database from
  before this column existed. `VIRTUAL` has no such restriction. The
  migration (`storage/db.py`) checks for the column's existence via
  `PRAGMA table_xinfo`, not `PRAGMA table_info` — the latter omits
  generated columns entirely and was verified to cause `init_db()` to
  crash on every database, including a freshly created one, by always
  believing the column was missing.
- `storage.reads.get_transactions()`'s `statements`/`cards` JOINs are
  built conditionally per-call based on which filters are actually
  present (`statement_month` needs `statements`; `bank`/`card_type` need
  `cards` too) — never joined unconditionally "just in case."
  `storage.reads.list_card_types()` applies the same "only cards with a
  statement" filter as `storage.cards.list_cards_with_statements()`, but
  lives in `storage/reads.py` and returns bank/card-type pairs rather
  than full card rows — a second, deliberate asymmetry alongside the
  `id`-vs-`created_at` ordering asymmetry already noted below.

## Open flags

- ~~`_BANK_PASSWORD_ENV_KEYS` and the bank-level parser call in
  `scripts/import_statement.py` are single-entry structures, hardcoded
  for HDFC only.~~ **Closed in Session 30**, generalized against two
  real banks: both collapsed into one module-level `_BANKS` registry
  (bank name -> password env key + dispatch package), so adding a bank
  is one entry rather than edits in two places. `storage.adapters`'
  `from_hdfc()` was checked at the same time and found to be already
  bank-agnostic — it reads only `parsers/base.py` contract fields — so
  it was renamed `from_parsed_statement()` with no body change.
  Card-type routing inside each bank's `parsers/<bank>/__init__.py` is
  unchanged and still per-bank by design.
- `storage.cards.list_cards()` orders by `created_at`;
  `storage.cards.list_cards_with_statements()` (Session 25) orders by
  `id` ASC instead. In practice these agree, since SQLite's
  `AUTOINCREMENT` id is assigned in insertion order, but it's a real (if
  inert) divergence between the two functions, not an accident.
- Card identity has two known, unfixed asymmetries: `storage.cards.
  create_card`'s bank/card_type matching is case-sensitive, but
  `parsers/hdfc`'s dispatch is case-insensitive; and cards with a `NULL`
  nickname can silently accumulate duplicates, since SQLite treats each
  `NULL` as distinct.
- Card identity convention clarified during Session 25 verification, and
  now backed by a real field as of Session 26: `nickname` must identify
  the physical card (e.g. `Primary`), never a statement period —
  `statements.statement_month` (generated from `period_end`) is the
  correct place for that, not the nickname. Future imports should attach
  to the existing card, not create a new one per month.
- Whether `GET /transactions` (and the three listing endpoints:
  `/cards`, `/statement-months`, `/card-types`) needs response
  pagination or a result-count cap is an open question — no evidence yet
  that it's a real problem.
- No index on `statements.statement_month` (Session 26) — explicit
  decision, not an omission. This is a single-user, local-file database
  with a small statement count; revisit only if that assumption stops
  holding.
- A `StarletteDeprecationWarning` (`httpx` with `starlette.testclient`)
  surfaced during Session 23's test run — unresolved, low-priority.
- Two visual-design items were raised during Session 44's frontend
  refresh and deliberately deferred: a stronger visual treatment for the
  Review & assign status line (it is currently a plain muted text line
  above the table), and a distinct typeface beyond the system font stack.
  Neither was built because the brief scoped that session to the system
  font stack and to styling within the existing layout. Both are open for
  a future, separately scoped frontend session; neither blocks anything.

## Next arc

The Tier 1 parser arc (Sessions 27–35) is complete: all four known bank
parsers are built, generalized behind one bank-agnostic registry, and
verified against every real sample statement on disk.

The project is now in the Expense Categorization & Analytics arc —
labelling transactions and surfacing spend insight on top of the existing
parse-and-store pipeline. Its scope, module breakdown, build order and
open questions are held in the expense categorization and analytics
vision document rather than restated here; that document is the source of
truth for this arc.

The preceding "HDFC UI end-to-end" arc (Sessions 23–26) and the
second-bank/generalization work that followed it are both done, and the
parser-tier roadmap in docs/PRODUCT_VISION.md is deliberately on hold
while the current arc runs.

## How this project works

See docs/CONVENTIONS.md for the full session methodology, DEVLOG entry
structure, learning summary format, data handling rules, and CLI
invocation convention. In short: scope is locked before code, Claude
Code builds, Chandra verifies in a separate terminal, and every session
ends in one commit covering code and docs together.
