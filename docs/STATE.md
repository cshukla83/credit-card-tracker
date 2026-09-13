# Project State

Always-current snapshot of the credit card statement tracker. Read this
first — it's the fastest way to get oriented. For the full session-by-
session history, see docs/DEVLOG.md. For process rules, see
docs/CONVENTIONS.md.

## What this is

A personal credit card statement tracker, built session by session as a
deliberate, hands-on vehicle for learning Claude Code. It parses monthly
PDF credit card statements, persists parsed transactions to a local
SQLite database, exposes that data through a queryable API, and — as of
the current arc — lets the user label every transaction with a category,
subcategory, and merchant through a single-page review screen with
learned suggestions.

Four bank/card types are implemented and reconciling: HDFC Diners (across
two known statement layouts, a current template and an older "legacy"
one, auto-detected from the PDF's own text), ICICI Coral, SBI Titan, and
IndusInd Legend. Axis remains an identified future target, not yet
started.

## Current state

As of Session 58 (**361 tests passing**, confirmed by running the suite in
Session 59; working tree clean), the project has two layers.

**Parse-and-store (Sessions 1–35), unchanged since.** The import pipeline
works end-to-end against real sample statements for four banks — HDFC
Diners (both layouts), ICICI Coral, SBI Titan, and IndusInd Legend — and
is bank-agnostic from the CLI down: parsing, an adapter bridging parser
output to storage (`from_parsed_statement`, shared by all four banks),
atomic deduped writes, and three command-line tools (`create_card`,
`import_statement`, `query_transactions`). All 18 real sample statements
on disk — six HDFC, four ICICI, four SBI, four IndusInd — parse and
reconcile against each statement's own summary totals, every one covered
by a committed integration test, and all 18 are loaded into the local
database for manual testing (336 transactions; the 2026-09-12 data note
in the DEVLOG, between Sessions 43 and 44).

**Categorization (Sessions 41–58), Module 2 of the expense analytics
arc.** `transactions` carries three nullable free-text labels —
`category`, `subcategory`, `merchant` — each added by the same
`table_xinfo`-guarded migration, each Title-Cased on write by one shared
rule, `NULL` the only representation of "unset" (`docs/DATA_MODEL.md`).
Three suggestion engines, deliberately different in shape, run off one
labelled-rows query per request:

- *category*: exact (case-insensitive description match, majority vote,
  confidence = winning share) then fuzzy (`difflib` ratio, best match, no
  floor), global across all cards; cold start → `none`.
- *subcategory*: exact only, scoped to rows sharing the transaction's own
  category; nothing until the row has a category; otherwise falls back to
  the category value itself (`same_as_category`, shown in words, not as a
  percentage).
- *merchant*: category's exact and fuzzy tiers on the merchant field,
  global; plus a fallback tier category lacks — the raw description
  (`from_description`, confidence null, shown in words).

Endpoints: `GET /transactions/{id}/suggestion` and
`POST /transactions/suggestions` (one batch, one labelled-rows query,
shape `{category, subcategory | null, merchant}`);
`POST /transactions/category` taking per-field-optional entries
`{transaction_id, category?, subcategory?, merchant?}` written atomically
(any unknown id → 404, nothing written); `GET /categories`,
`GET /subcategories?category=`, `GET /merchants`; and
`POST /transactions/clusters` — anchor-based description clustering at a
0–100 threshold: walk in the given order, each unplaced row anchors a
cluster, later rows join if their similarity *to that anchor* meets the
threshold (not transitive, so order-dependent by design), clusters of one
are dropped entirely, each member reports its similarity to the anchor.

Frontend (`static/index.html`, still one file, no framework): two tabs
over one filter bar. The filter bar is a Bank → Card cascade plus
statement month and date range, with **bidirectional narrowing** — every
picker's options are recomputed from the listing endpoints using all
filters except its own (Bank also omits Card; picking a card snaps Bank to
its bank), date inputs bounded by the real data, invalidated selections
kept and flagged rather than silently cleared, URL as source of truth on
load, and a second sequence counter guarding the pickers. **As of Session
75 the mesh includes category, subcategory, and merchant on the API side**
(frontend dropdowns added in Session 76 as a second filter-bar row —
Category, Subcategory, Merchant — on all three tabs, each always offering a
synthetic "Uncategorized" option): `/categories`, `/subcategories`,
and `/merchants` are narrowed by bank / card / card type / statement month
/ date range, and `/cards`, `/statement-months`, `/card-types`, and
`/transactions` are narrowed by the three labels in return — with **one
deliberate exception: the three labels do not narrow each other.** They
are independent peers, selected in any combination, not a cascade like
Bank → Card — mirroring the chart's design in which the three are chosen
independently. (`/subcategories?category=` remains the review screen's
per-row editor scope, unchanged, and is not part of the mesh.) *All
transactions* lists rows read-only with merchant/category/subcategory.
*Review & assign* groups rows either by suggested category (default) or by
description similarity at a chosen threshold; each row shows its
suggestions with accept/change for all three labels (one-click dropdown,
spread-to-group, add-new); a sticky multi-select bar offers typed bulk
assign and per-field bulk accept for category and merchant (merchant bulk
excludes `from_description`), with a Category/Merchant display toggle.
*Dashboard* (Sessions 65–69, 73–77): period controls (week / month /
quarter / year / custom, relative or absolute), the resolved period and
total echoed from the API, a Chart.js bar chart, a collapsible table, and
an on-demand LLM "insight" with fresh / cached / unavailable states. **As
of Session 77 the chart is a permutable three-level drill** over Merchant
/ Category / Subcategory: three "Level 1/2/3 =" selects hold a permutation
(swap-on-conflict; default Merchant → Category → Subcategory), the tab
always fetches `dimensions=<level1>,<level2>,<level3>`, and the bars shown
are the first level whose dimension has no active filter — computed as
1 + the count of contiguous filtered levels from Level 1. Clicking a bar
**sets that dimension's filter dropdown** (Session 76's row) and goes
through the ordinary filter-change path; "back" is clearing the dropdown.
There is no separate drill state — the filters are the drill — but since
Session 78 a **breadcrumb strip** above the chart shows the path ("All ›
Merchant: X › Category: Y", in the current order, skipping unfiltered
levels); clicking a crumb clears that level's filter and every level
after it, "All" clears all three, both through the ordinary filter-change
path. Added after manual verification of Session 77 found the dropdowns
alone insufficient as a way to see the position and step back. The table
below always shows the whole three-level tree in the current order,
collapsible at every level. Order round-trips in the URL (`d_order`).
Groups are collapsible; the visual system is CSS-variable based with a
system font stack.

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
  `fetch()`-based consumer of the API — it never reaches into the
  database directly, and never exposes anything the endpoints don't
  already return.
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
- Read-path JOINs are built per-call from which filters are actually
  present (`statement_month` needs `statements`; `bank`/`card_type` need
  `cards` too) — never joined unconditionally "just in case." One
  qualified exception since Session 63: `get_transactions()` always joins
  `statements` and `cards` because its rows now *return* `card_id` and
  `bank`; that join is needed for the output, not speculatively. The
  listing queries still join only what their filters need.
  `storage.reads.list_card_types()` applies the same "only cards with a
  statement" filter as `storage.cards.list_cards_with_statements()`, but
  lives in `storage/reads.py` and returns bank/card-type pairs rather
  than full card rows — a second, deliberate asymmetry alongside the
  `id`-vs-`created_at` ordering asymmetry already noted below.
- The read-path filter set has **one definition**:
  `storage.reads.filter_sql(anchor, ...)` (Session 45) builds the JOIN and
  WHERE clauses for a query anchored on `cards`, `statements`, or
  `transactions`, joining only the tables the active filters need.
  `get_transactions()` and all three listing endpoints use it; each
  listing accepts every filter except the one dimension it *is*, so a
  picker can never narrow itself. Since Session 74 it also takes three
  independently combinable label filters — `category`, `subcategory`,
  `merchant` — columns on `transactions` (no extra JOIN), normalised with
  the same Title Case rule as the write path (now
  `storage.normalize.normalize_label`, re-exported by `main.py`), with
  the value **"Uncategorized" meaning `IS NULL`** — the deliberate
  inverse of aggregation's NULL → "Uncategorized" output folding.
- **Aggregation is one query, any order of nesting** (Session 74):
  `storage.aggregate.aggregate_spend(..., dimensions=[...])` always runs
  the single finest `GROUP BY category, subcategory, merchant`, folds NULL
  to "Uncategorized" on all three, and builds the tree in Python in the
  caller's order — 2 or 3 distinct names, default
  `["category", "subcategory"]` reproducing the Session 65 shape exactly.
  Node keys adapt to the dimension at each level (`categories` /
  `subcategories` / `merchants`); sort is amount-descending at every
  level. This replaced Session 73's `depth` parameter outright rather than
  alongside it — no external consumer of either, so reshaping in place
  carried no compatibility cost. `GET /transactions/aggregate` exposes
  `dimensions` as a comma-separated param and the three label filters.
- **Fuzzy similarity has one definition**:
  `storage.categories.fuzzy_similarity()` (Session 50) — `difflib`
  `SequenceMatcher.ratio()` over casefolded strings. The category and
  merchant suggestion engines' Tier 2 and the clustering endpoint all call
  it; Tier 1 exact matching and Tier 2 fuzzy matching are themselves
  shared, field-generic helpers (`_exact_tier`, `_fuzzy_tier`, Session
  55) rather than copies per label.
- **One normalization rule for all three text labels**:
  `normalize_category()` in `main.py` — `strip().title()`, reject empty —
  applied by the API's validator to `category`, `subcategory`, and
  `merchant` alike (Sessions 49, 53, 55). `str.title()`'s behaviour on
  apostrophes/hyphens (`"Mcdonald'S"`) is a known, tested, accepted
  limitation, not to be special-cased until a real case hurts.
- **Every "accept" writes the client-displayed suggestion**, never a
  recompute (Session 43 onward): the frontend sends the value it showed,
  and the assign endpoint is a direct write that never consults the
  engine.
- **Tie-breaks use highest transaction id as a proxy for "most recently
  assigned"** (Session 41): no assignment timestamp exists, so most
  recently *imported* stands in, and the ordering falls out of an
  id-`DESC` query plus `Counter.most_common()` first-seen order. Adding a
  `category_assigned_at` column is its own decision, not taken.
- **Suggestion labels distinguish learned from default**: a percentage
  only for `exact`/`fuzzy`; the words "same as category" /
  "from description" for the fallback tiers, whose 1.0/null confidence is
  a default, not evidence (Sessions 53–56). Bulk merchant accept excludes
  `from_description` for the same reason (Session 57).
- **The suggestion engines never write.** Every label reaches the
  database only through `POST /transactions/category`; suggestion
  endpoints are pure reads.

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
- No min/max-date endpoint (Session 46). The frontend bounds the Start
  and End date inputs by the earliest and latest transaction dates in the
  undated filtered set. When no date filter is set, the table's own
  result is that set and no extra request is made; when one *is* set,
  the frontend fetches the full undated `/transactions` list just to
  derive two dates. Deliberately not built as an endpoint: at this
  project's data size the extra fetch is negligible. Revisit — a small
  `GET /transactions/date-range` taking the same filters — only if real
  usage shows the undated fetch's cost.
- **Manual visual verification gap.** Every frontend session from 43
  through 58 was verified by parsing the script (system JavaScriptCore)
  and reasoning through the code — **none of it has been seen rendered
  by Claude Code**, because the browser extension was unavailable in each
  of those sessions, and the project's convention keeps live-server
  verification with Chandra. That covers: the Review & assign screen and
  both grouping modes, the Bank/Card cascade and narrowing, the visual
  refresh, collapsible groups, the sticky bar and header parking, the
  Category/Merchant toggle, and all three label columns with their
  editors. Each of those sessions' DEVLOG entries says so plainly and
  lists what a manual walk should cover; until that walk happens, the
  frontend's behaviour is what the code specifies, not what has been
  observed. Two real bugs were caught by code trace alone in that stretch
  (a disabled-buttons regression in Session 43, a dropdown-clipping bug in
  Session 44); more may be waiting.
- **The selection count can include rows that are not on screen.** After
  a bulk accept from the multi-select bar (Session 57) the selection is
  deliberately kept whole and the post-reload prune is skipped, so the
  other bulk button can act on the same rows — but under "Uncategorized
  only", rows that just received a category leave the visible groups
  while staying selected. In similarity mode the selection is likewise
  pruned to the filtered set, not to the rows above threshold (Session
  51). In both cases the bar's "N selected" is true of the filtered set,
  not of what is visible; "clear selection" resets it. Acceptable for
  now; revisit if it confuses in use.
- `GET /transactions/{id}/suggestion` and `POST /transactions/suggestions`
  changed shape incompatibly three times in three sessions (53, 55; the
  assign body likewise in 42, 53, 55), each deliberately and each pinned
  by tests. Nothing outside this repository consumes them, so no
  versioning was added; if a second consumer ever appears, that is the
  moment to stop reshaping in place.
- **Review & assign inline editing.** The category, subcategory, and
  merchant editors on the Review & assign screen rely on several buttons
  per row — accept, a change dropdown, spread-to-group inside it, add-new
  — plus the sticky multi-select bar's bulk actions, and the result has
  been flagged as too cluttered. A future session should scope an
  inline-edit interaction (for example, click-to-edit on the cell) to
  replace or reduce that button surface. Not yet scoped, and not to be
  guessed at here: how inline editing would coexist with the suggestion
  badges, with the multi-select bar, and with the card-payment cascade
  (Session 62), all of which currently depend on the button-based
  interaction. Recorded so it isn't lost; nothing decided.
- **Table header not sticky.** The column header row (date, description,
  type, and so on) on both the Review & assign and All transactions
  tables scrolls out of view, whereas the multi-select bar (made sticky
  in Session 58) stays put. A future session should make the header
  sticky using the same pattern, with attention to z-index layering
  against the multi-select bar — and against the group headers that
  already park beneath it — when all are visible at once. Recorded, not
  designed.
- **No "collapse all" for groups.** Groups on Review & assign are
  individually collapsible in both grouping modes (collapsing added in
  Session 44; per-group defaults in Session 52) but there is no bulk
  toggle. A future session should add a "collapse all" / "expand all"
  control. Recorded, not designed.

## Next arc

The Tier 1 parser arc (Sessions 27–35) is complete: all four known bank
parsers are built, generalized behind one bank-agnostic registry, and
verified against every real sample statement on disk.

The project is in the Expense Categorization & Analytics arc. Against that
document's build sequence, **steps 1 and 2 — the categorization data model
and suggestion engines, and the review/assign screen with bulk apply —
are built** (Sessions 41–58), and grew beyond their original scope with
subcategory and merchant labels and a similarity-grouping mode. They are
built, tested at the API level, and **not yet manually verified in a
browser** (see Open flags); that walk is the gate before calling Module 2
done. Step 3 — the aggregation endpoint and analytics dashboard with
filters and LLM commentary (Module 3) — is next in sequence, and step 4
(upload with auto-detect, Module 1) after it. Scope, open questions, and
sequencing remain in the vision document, which is the source of truth
for this arc.

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
