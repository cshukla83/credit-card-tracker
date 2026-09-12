# Data Model

The SQLite schema as it is actually defined in code, generated from ground
truth rather than from other documents.

**Source of truth:** `storage/schema.py` (the four `CREATE TABLE`
statements plus the `ALTER TABLE` migrations) and `storage/db.py` (how
they are applied). Everything below was checked against those files and
then confirmed by building a throwaway in-memory database from
`storage/schema.py` and introspecting it with `PRAGMA table_xinfo`,
`PRAGMA index_list`, `PRAGMA index_info`, and `PRAGMA foreign_key_list`
(SQLite 3.50.4, the version bundled with the project's Python). No
connection was made to `data/tracker.db` and no real rows were read.

**Scope:** what exists today. This document does not describe planned
columns or tables; when the schema changes, this file should change in the
same commit.

---

## Overview

Three application tables in a strict parent → child → grandchild chain:

```
cards  1 ──< N  statements  1 ──< N  transactions
```

- One **card** has many **statements** (one per billing period).
- One **statement** has many **transactions**.
- Deleting a card cascades to its statements and, through them, to their
  transactions. Deleting a statement cascades to its transactions.

One further, standalone table — `commentary_cache` (Session 68) — holds
the latest LLM commentary per dashboard view; it has no foreign keys and
sits outside the chain. See its section below. SQLite also maintains an internal
`sqlite_sequence` table because every `id` column uses `AUTOINCREMENT`;
it is not part of the application model and is never referenced by code.

### How the schema is applied

`storage.db.init_db()` runs the four `CREATE TABLE IF NOT EXISTS`
statements, then five column migrations of identical shape, each of which
checks `PRAGMA table_xinfo(<table>)` for the column and runs
`ALTER TABLE ... ADD COLUMN` only if it is absent:

- `_ensure_statement_month_column()` → `statements.statement_month`
  (Session 26). `PRAGMA table_xinfo` (not `table_info`) is required here
  because `table_info` omits generated columns — see the comment in
  `storage/db.py` and DEVLOG Session 26.
- `_ensure_category_column()` → `transactions.category` (Session 41).
  A plain column, so `table_info` would also work; `table_xinfo` is used
  for consistency.
- `_ensure_subcategory_column()` → `transactions.subcategory` (Session
  53). Same idiom as `category`.
- `_ensure_merchant_column()` → `transactions.merchant` (Session 55).
  Same idiom again.
- `_ensure_is_payment_column()` → `transactions.is_payment` (Session 61).
  Same idiom; the only one whose `ADD COLUMN` carries `NOT NULL DEFAULT
  0`, which SQLite permits and uses to back-fill existing rows.

All five `ALTER TABLE` statements live in `storage/schema.py` next to the
`CREATE TABLE` they must stay identical to.

Every connection from `storage.db.get_connection()` sets
`PRAGMA foreign_keys = ON`. This matters: SQLite does not enforce foreign
keys (or run `ON DELETE CASCADE`) unless that pragma is on for the
connection, so the FK behaviour described below holds only for
connections opened through `get_connection()`.

### A note on SQLite column types

SQLite uses *type affinity*, not strict types. The declared types below
are what the `CREATE TABLE` statements say; the actual storage class of a
value depends on what is bound. In practice:

- `DATE` and `TIMESTAMP` are not native SQLite types. They resolve to
  NUMERIC affinity, and the code stores ISO-8601 strings in them
  (`storage.dates.to_date_str()` converts `date` objects to `YYYY-MM-DD`
  before binding; `CURRENT_TIMESTAMP` defaults produce `YYYY-MM-DD
  HH:MM:SS` UTC strings). Comparisons and `strftime()` on these columns
  work because the strings are ISO-formatted, not because SQLite knows
  they are dates.
- `REAL` columns accept integers; SQLite stores them as REAL-affinity
  values and Python reads them back as `float`.

---

## Table: `cards`

One physical credit card, identified by bank, card type, and an optional
nickname.

| Column       | Declared type | Constraints                                 |
|--------------|---------------|---------------------------------------------|
| `id`         | `INTEGER`     | `PRIMARY KEY AUTOINCREMENT`                 |
| `bank`       | `TEXT`        | `NOT NULL`                                  |
| `card_type`  | `TEXT`        | `NOT NULL`                                  |
| `nickname`   | `TEXT`        | nullable                                    |
| `created_at` | `TIMESTAMP`   | `NOT NULL DEFAULT CURRENT_TIMESTAMP`        |

**Table constraints**

- `UNIQUE(bank, card_type, nickname)`

**Design notes (documented elsewhere — pointers only)**

- `nickname` may be `NULL`, and SQLite treats each `NULL` as distinct in a
  `UNIQUE` constraint, so multiple cards with the same `(bank, card_type)`
  and no nickname are allowed *by design*. Lookups with `nickname=None`
  therefore use an explicit `IS NULL`. See STATE.md ("Card lookups by
  nickname…") and DEVLOG Session 18 (decision) / Session 22 (consequence).
- `bank` and `card_type` comparisons in the `UNIQUE` constraint are
  case-sensitive (SQLite default `TEXT` collation), while the parser
  dispatch layer normalises case — a known, unfixed asymmetry. See
  STATE.md ("Card identity has two known, unfixed asymmetries") and
  DEVLOG Session 22.
- `nickname` is meant to identify the physical card, never a statement
  period — see STATE.md ("Card identity convention…").
- There is no `CHECK` or enum constraint on `bank` or `card_type`; any
  text is accepted at the storage layer. The set of banks the application
  can actually *parse* is defined by the `_BANKS` registry in
  `scripts/import_statement.py` (keyed by the exact `cards.bank` string),
  not by the schema.

---

## Table: `statements`

One imported billing-period statement for a card.

| Column            | Declared type | Constraints                                                                 |
|-------------------|---------------|-----------------------------------------------------------------------------|
| `id`              | `INTEGER`     | `PRIMARY KEY AUTOINCREMENT`                                                 |
| `card_id`         | `INTEGER`     | `NOT NULL`, `FOREIGN KEY → cards(id) ON DELETE CASCADE`                     |
| `period_start`    | `DATE`        | `NOT NULL`                                                                  |
| `period_end`      | `DATE`        | `NOT NULL`                                                                  |
| `imported_at`     | `TIMESTAMP`   | `NOT NULL DEFAULT CURRENT_TIMESTAMP`                                        |
| `statement_month` | `TEXT`        | `GENERATED ALWAYS AS (<expression>) VIRTUAL` — computed, nullable, read-only |

**Table constraints**

- `UNIQUE(card_id, period_start, period_end)` — this is the import
  de-duplication key. `storage.writes.insert_statement()` relies on it:
  a collision returns `None` (silent skip) instead of raising.
- `FOREIGN KEY(card_id) REFERENCES cards(id) ON DELETE CASCADE`
  (`ON UPDATE` is the default `NO ACTION`).

**`statement_month` in detail**

- Derived entirely from `period_end`: the full English month name of
  `period_end`, a hyphen, and the four-digit year (for example the
  pattern `<MonthName>-<YYYY>`). The month name is produced by an inline
  `CASE` over `strftime('%m', period_end)` because SQLite's `strftime`
  has no month-name specifier. The expression lives once in
  `storage/schema.py` as `STATEMENT_MONTH_EXPRESSION` and is shared
  between the `CREATE TABLE` and the `ALTER TABLE` migration so fresh and
  migrated databases have byte-identical definitions.
- `VIRTUAL`, not `STORED`: computed on read, never written to disk.
  Chosen because SQLite refuses to `ALTER TABLE ... ADD COLUMN` a `STORED`
  generated column onto a table that already has rows, which is exactly
  the migration case. See the comment on `ADD_STATEMENT_MONTH_COLUMN` in
  `storage/schema.py` and DEVLOG Session 26.
- The schema declares no `NOT NULL` on it (SQLite would allow one), so it
  is nominally nullable — but it can never actually be `NULL` because
  `period_end` is `NOT NULL` and the expression always yields a string.
- `PRAGMA table_xinfo` reports it with `hidden = 2` (the VIRTUAL
  generated-column marker). `PRAGMA table_info` does not report it at
  all.
- It cannot be inserted into or updated; it is filtered on in
  `storage.reads.get_transactions()` and listed by
  `storage.reads.list_statement_months()`.

---

## Table: `transactions`

One line item from a statement, as extracted by the bank-specific parser.

| Column          | Declared type | Constraints                                                        |
|-----------------|---------------|--------------------------------------------------------------------|
| `id`            | `INTEGER`     | `PRIMARY KEY AUTOINCREMENT`                                        |
| `statement_id`  | `INTEGER`     | `NOT NULL`, `FOREIGN KEY → statements(id) ON DELETE CASCADE`       |
| `txn_date`      | `DATE`        | `NOT NULL`                                                         |
| `description`   | `TEXT`        | `NOT NULL`                                                         |
| `amount`        | `REAL`        | `NOT NULL`                                                         |
| `txn_type`      | `TEXT`        | `NOT NULL`                                                         |
| `reward_points` | `REAL`        | nullable                                                           |
| `category`      | `TEXT`        | nullable — `NULL` means uncategorized                              |
| `subcategory`   | `TEXT`        | nullable — `NULL` means no subcategory                             |
| `merchant`      | `TEXT`        | nullable — `NULL` means no merchant label                          |
| `is_payment`    | `INTEGER`     | `NOT NULL DEFAULT 0` — boolean 0/1, never `NULL`                    |

**Table constraints**

- `FOREIGN KEY(statement_id) REFERENCES statements(id) ON DELETE CASCADE`
  (`ON UPDATE` is the default `NO ACTION`).
- No `UNIQUE` constraint. Two identical rows within one statement are
  legal — de-duplication happens one level up, at the statement.

**Column semantics**

- **`description` is the merchant/payee column.** There is no separate
  merchant, payee, or normalised-name column. It holds the **raw string
  as captured by the parser's regex from the PDF's text layer, with only
  leading/trailing whitespace stripped** (`match.group("desc").strip()`
  in every parser: `parsers/hdfc_diners.py`, `parsers/hdfc_diners_legacy.py`,
  `parsers/icici_coral.py`, `parsers/indusind/indusind_legend.py`,
  `parsers/sbi/sbi_titan.py`). Nothing between the parser and the
  `INSERT` touches its content:
  - `parsers/base.Transaction.description` is the parser output field.
  - `storage/adapters._FIELD_MAP` renames it `description → description`
    (identity) and performs no transformation.
  - `storage/writes.insert_statement()` binds `txn["description"]`
    directly.

  Consequences worth knowing before building anything on top of it:
  no case-folding, no collapsing of internal whitespace, no removal of
  city/location suffixes, reference numbers, or category text that the
  bank glues into the same PDF column. Where a bank's layout puts a
  reference number in its own column (ICICI), the parser captures it
  separately and *discards* it — it is not appended to `description`.
  Where a description wraps onto a second PDF line (IndusInd), only the
  fragment on the dated line is kept. Any two statements — even from the
  same bank — may spell the same merchant differently, and the column
  faithfully preserves those differences. The HDFC parser does
  upper-case a *copy* of the description to classify `txn_type`, but
  stores the original.

- **`txn_type`** is either `"debit"` or `"credit"` by convention
  (`parsers/base.Transaction.type` comment) — there is **no `CHECK`
  constraint** enforcing this; the schema accepts any non-null text.

- **`amount`** is always a non-negative magnitude; direction is carried by
  `txn_type`, not by sign.

- **`txn_date`** is a pure date. Parsers emit a `datetime` (some layouts
  carry time-of-day); `storage/adapters._map_transaction()` drops the time
  component before storage.

- **`reward_points`** is declared `REAL` although every parser produces an
  `int` (or `None` when the statement has no points column for that
  line). Sign is meaningful: the HDFC parser emits negative values for
  points reversals.

- **`category`** (Session 41) is the user-assigned, free-text spend
  category. `NULL` is the only representation of "uncategorized" — the
  code never writes an empty string (`storage.categories.assign_categories()`
  rejects one, and the API strips whitespace and rejects the result if
  empty). There is no `CHECK` constraint and no categories table: the set
  of categories is simply the distinct non-null values in this column.
  Import never sets it; only the assign endpoint does. The suggestion
  engine (`storage.categories.suggest_category()`) reads it globally
  across all cards, excluding the transaction being suggested for.
  **No assignment timestamp is recorded**, so "most recently assigned"
  is not knowable; the engine's tie-break uses highest `id` (most
  recently *imported*) as a documented proxy.

- **`subcategory`** (Session 53) is a second, finer free-text label under
  `category`, with the same rules: nullable, `NULL` is the only
  representation of "not set", never an empty string, Title-Cased on
  write by the API, no `CHECK`, no lookup table — the set of
  subcategories is the distinct non-null values (optionally per
  `category`, via `GET /subcategories?category=`). It is **not
  constrained to be non-null only when `category` is set**: the assign
  endpoint writes whichever of the two fields a request carries and
  leaves the other alone, so a row *can* hold a subcategory with a
  `NULL` category. The subcategory suggestion engine, by contrast,
  returns nothing for a row until its `category` is set; it has no
  fuzzy tier and falls back to the row's own `category` value
  (`match_type "same_as_category"`).

- **`merchant`** (Session 55) is a user-assigned, free-text merchant
  label — a cleaned-up name for the raw `description`. Same storage
  rules as the other two labels: nullable, `NULL` is the only "not set",
  never an empty string, Title-Cased on write, no `CHECK`, no lookup
  table (`GET /merchants` is the distinct non-null values, unscoped).
  Independent of `category`: it can be set with or without one. Its
  suggestion engine reuses category's exact and fuzzy tiers over rows
  with a non-null merchant — globally, not scoped by category — and,
  unlike category, always yields a value: with nothing to learn from it
  proposes the row's own raw `description` (`match_type
  "from_description"`, confidence `null`). The one labelled-rows query
  behind all three engines selects rows with a non-null `category` **or**
  `merchant`.

- **`is_payment`** (Session 61) marks a credit line that is a payment
  *to* the card (the cardholder paying the bill), as opposed to a refund
  credit. Boolean, not tri-state: `NOT NULL DEFAULT 0`, so unlike the
  three text labels there is no "unset". It is set at import time by
  each bank's parser from that bank's own statement text (a fixed lead
  token on payment lines; the token lists live in the parser modules, not
  here), and can be changed through the assign endpoint. It is only ever
  meaningful for `txn_type = "credit"`; the endpoint rejects `1` on a
  debit with 400 and writes nothing. **No `CHECK` constraint enforces
  that** — the column will accept `1` on a debit if written directly —
  the invariant lives in `storage.categories.assign_categories()` and in
  the parsers, which never flag a debit. Writing it through the endpoint
  cascades: `0 → 1` also sets `category` and `subcategory` to the
  payment label and `merchant` to the card's `bank` (verbatim, not
  Title-Cased); `1 → 0` sets all three back to `NULL`. Import sets only
  the flag, never the labels.

---

## Table: `commentary_cache`

The latest LLM-generated commentary for one dashboard view (Session 68).
Standalone: no foreign keys, not part of the cards → statements →
transactions chain, and never joined to it.

| Column            | Declared type | Constraints                                  |
|-------------------|---------------|----------------------------------------------|
| `id`              | `INTEGER`     | `PRIMARY KEY AUTOINCREMENT`                  |
| `query_signature` | `TEXT`        | `NOT NULL UNIQUE`                            |
| `commentary`      | `TEXT`        | `NOT NULL`                                   |
| `generated_at`    | `TIMESTAMP`   | `NOT NULL DEFAULT CURRENT_TIMESTAMP` (UTC)   |

- **`query_signature`** identifies a *resolved* view: the period's
  start and end dates (after `resolve_period()`), plus the `bank`,
  `card_id`, and `card_type` filters, each normalised (stripped; an
  absent filter written as a fixed sentinel). It is deliberately not
  built from the raw granularity/mode/count parameters, so two requests
  that resolve to the same dates share one row. Built by
  `storage.commentary.query_signature()`.
- Writes are UPSERTs on `query_signature`: only the most recent
  successful commentary per view is kept, and `generated_at` is reset on
  each replacement. `UNIQUE` gives this table its one auto-index.
- Created by a plain `CREATE TABLE IF NOT EXISTS` in `init_db()`; being a
  new table, it needs no `table_xinfo`-guarded migration.
- Rows are written only after a successful model call; a failed call
  reads this table but never writes it.

---

## Foreign key relationships

| Child table.column          | Parent table.column | Cardinality (parent : child) | On delete | On update  |
|-----------------------------|---------------------|------------------------------|-----------|------------|
| `statements.card_id`        | `cards.id`          | 1 : N (a card has 0..N statements; a statement has exactly 1 card)        | `CASCADE` | `NO ACTION` |
| `transactions.statement_id` | `statements.id`     | 1 : N (a statement has 0..N transactions; a transaction has exactly 1 statement) | `CASCADE` | `NO ACTION` |

Both FKs are `NOT NULL`, so orphan rows are impossible while
`PRAGMA foreign_keys = ON` is in effect. `insert_statement()` distinguishes
an FK violation (bad `card_id` → re-raised) from a `UNIQUE` violation
(duplicate statement → returns `None`) via `sqlite_errorname`; see
`storage/writes.py`.

Enforcement is per-connection and depends on the pragma. A connection
opened with bare `sqlite3.connect()` (as the legacy-schema test fixture in
`tests/test_storage.py` does) would not enforce these.

---

## Indexes

The codebase contains **no `CREATE INDEX` statement anywhere** — not in
`storage/schema.py`, not in `storage/db.py`, not in any script or test.
That is not the same as "no indexes": SQLite creates an index
automatically for each `UNIQUE` table constraint, and those exist on disk.

**Indexes that exist (all SQLite-generated):**

| Index name                      | Table        | Columns (in order)                        | Unique | Origin                          |
|---------------------------------|--------------|-------------------------------------------|--------|---------------------------------|
| `sqlite_autoindex_cards_1`      | `cards`      | `bank`, `card_type`, `nickname`           | yes    | `UNIQUE(bank, card_type, nickname)` |
| `sqlite_autoindex_statements_1` | `statements` | `card_id`, `period_start`, `period_end`   | yes    | `UNIQUE(card_id, period_start, period_end)` |

Each `INTEGER PRIMARY KEY` column is the table's rowid and needs no
separate index. (`AUTOINCREMENT` only affects id reuse; it does not add an
index.)

**`transactions` has no index of any kind** — not on `statement_id`, not
on `txn_date`, not on `description`, not on `category`.

**Omissions:**

- `statements.statement_month` — **deliberately** not indexed. Recorded
  decision: single-user, local-file database with a small statement
  count; see STATE.md ("No index on `statements.statement_month`") and
  DEVLOG Session 26. (As a `VIRTUAL` generated column it could still be
  indexed if that ever changed.)
- `statements.card_id` — not separately indexed. Note that it is the
  *leading* column of `sqlite_autoindex_statements_1`, so lookups and
  the cascade from `cards` can use that index.
- `transactions.statement_id` — not indexed, and it is the FK column
  every `ON DELETE CASCADE` from `statements` and every
  `JOIN statements ON transactions.statement_id = statements.id` in
  `storage/reads.py` walks. **No recorded decision** exists for this one
  in STATE.md or the DEVLOG; it is an observed absence, not a documented
  choice. The same small-data reasoning as `statement_month` presumably
  applies, but it has not been stated.
- `transactions.txn_date` — not indexed, though it is the sort key of
  every `get_transactions()` query and the column its date-range filters
  use. Same status as above: observed, not decided.

---

## Quick reference: `CREATE TABLE` as defined

Reproduced from `storage/schema.py` for readers who want the exact SQL.
The `statement_month` expression is elided here; see the file.

```sql
CREATE TABLE IF NOT EXISTS cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bank TEXT NOT NULL,
    card_type TEXT NOT NULL,
    nickname TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(bank, card_type, nickname)
);

CREATE TABLE IF NOT EXISTS statements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id INTEGER NOT NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    imported_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    statement_month TEXT GENERATED ALWAYS AS (/* see STATEMENT_MONTH_EXPRESSION */) VIRTUAL,
    FOREIGN KEY(card_id) REFERENCES cards(id) ON DELETE CASCADE,
    UNIQUE(card_id, period_start, period_end)
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    statement_id INTEGER NOT NULL,
    txn_date DATE NOT NULL,
    description TEXT NOT NULL,
    amount REAL NOT NULL,
    txn_type TEXT NOT NULL,
    reward_points REAL,
    category TEXT,
    subcategory TEXT,
    merchant TEXT,
    is_payment INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(statement_id) REFERENCES statements(id) ON DELETE CASCADE
);
```
