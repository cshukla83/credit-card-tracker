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

As of Session 23 (91 tests passing, working tree clean), the HDFC Diners
pipeline works end-to-end against real sample statements: parsing (both
layouts), an adapter bridging parser output to storage, atomic deduped
writes, a filtered read path, and a `GET /transactions` FastAPI endpoint
wrapping that read path. Three command-line tools exist —
`create_card`, `import_statement`, and `query_transactions` — all
following the same shape, each documented with a usage docstring plus a
README section.

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
  collision on `id`.
- Card-type auto-detection from PDF content is explicitly deferred —
  `--card-id` is always required, never inferred.
- Single-user is implicit throughout — no auth, no user table, one local
  SQLite file.

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
- Whether `GET /transactions` needs response pagination or a
  result-count cap is an open question — no evidence yet that it's a
  real problem.
- A `StarletteDeprecationWarning` (`httpx` with `starlette.testclient`)
  surfaced during Session 23's test run — unresolved, low-priority.

## Next arc

The current arc, set on 2026-08-20, is "HDFC UI end-to-end": Session 23
(done) added the `/transactions` API endpoint. Session 24 is next — a
minimal HTML page consuming it, with server-rendered vs. client-side
fetch as the first scoping decision. Session 25 adds filters (a card
picker, a date range control). Session 26 onward is deliberately left
open, to be decided from what Sessions 23–25 actually reveal is needed,
not speculated now. Once the HDFC UI ships, the arc moves to a second
real bank (ICICI) — which is also when the deferred password-key and
dispatch-routing generalizations above finally happen, against two real
cases rather than speculatively.

## How this project works

See docs/CONVENTIONS.md for the full session methodology, DEVLOG entry
structure, learning summary format, data handling rules, and CLI
invocation convention. In short: scope is locked before code, Claude
Code builds, Chandra verifies in a separate terminal, and every session
ends in one commit covering code and docs together.
