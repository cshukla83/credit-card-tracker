# PRD: Credit Card Statement Tracker

## 0. Document Control
Version 1.5 — 14 Sep 2026 — Owner: Chandra — Consolidated from
STATE.md, PRODUCT_VISION.md, EXPENSE_ANALYTICS_VISION.md, CONVENTIONS.md.
This document is re-consolidated by hand whenever any of those source
docs change materially — it is not maintained independently of them.
(`scripts/generate_prd_docx.py` renders this file to Word; it does not
generate this file.)

## 1. Executive Summary
A personal credit card statement tracker, built session by session as a
deliberate, hands-on vehicle for learning Claude Code. It parses PDF
credit card statements from four Indian bank/card types — HDFC Diners
(two layouts), ICICI Coral, SBI Titan and IndusInd Legend, all
implemented and reconciling — stores transactions locally, lets the user
label each one with a category, subcategory and merchant through a
review screen with learned suggestions (built), and is being extended
with spend analytics (next).

## 2. Background
The project's original intent was not just to store statement data, but
to aggregate spend across cards and understand where money is going, so
it can be actively managed. Statement parsing and storage were built
first as the necessary foundation; categorization and analytics are the
layer that delivers on the original intent.

## 3. Goals
- Reliable, reconciled parsing across known Indian bank statement
  formats (HDFC Diners, ICICI Coral, SBI Titan, IndusInd Legend — all
  four complete and reconciling as of Session 35).
- A path to support new, previously-unseen bank formats without
  rearchitecting (the four-tier parser roadmap).
- Categorized transactions and commented spend insight, filterable by
  date range, month, quarter, and year.
- The project itself is a deliberate Claude Code learning vehicle —
  session discipline (locked scope, DEVLOG entries, single commits) is
  a project goal, not just process overhead.

## 4. Target User
Single user (Chandra), personal use. No multi-user support, no
authentication — explicit design decision, not a gap.

## 5. Scope
**In scope:** parsing Indian bank credit card statements; expanding
coverage to new banks via the parser-tier roadmap; expense
categorization; spend analytics dashboard; drag-and-drop statement
upload.

**Out of scope (explicit):** multi-user support; budgets or alerts with
notifications; any external data source (bank APIs, account
aggregators).

## 6. Prioritized Requirements Index

| Priority | # | Requirement | Status | Source |
|---|---|---|---|---|
| P0 | 1 | Categorization data model + suggestion engines (category, subcategory, merchant) | **Built** (Sessions 41–55) | EXPENSE_ANALYTICS_VISION.md, Module 2 |
| P0 | 2 | Categorization review/assign screen, incl. multi-select bulk actions and two grouping modes | **Built, awaiting manual browser verification** (Sessions 43–58) | Module 2 |
| P0 | 3 | Aggregation endpoint + dashboard (filters + LLM commentary) | **Built, awaiting manual browser verification** (Sessions 65–69, 73–77) | Module 3 |
| P0 | 4 | Upload UI with bank/card auto-detect | **Built, awaiting manual browser verification** (Sessions 97–101; endpoints verified live under a one-time exception) | Module 1 |
| P1 | 5 | Parser config schema (prerequisite for all remaining tiers) | Not started | PRODUCT_VISION.md |
| P1 | 6 | Tier 4 — LLM auto-learn parser generation | Not started | PRODUCT_VISION.md |
| P1 | 7 | Tier 3 — Guided manual config wizard | Not started | PRODUCT_VISION.md |
| P1 | 8 | Tier 2 — Community-shared configs (depends on 6 or 7) | Not started | PRODUCT_VISION.md |
| P2 | 9 | HTML page value formatting (dates, amounts) | Open, unscheduled | STATE.md |
| P2 | 10 | Statements-list API (a card's statements/periods) | Open, unscheduled | STATE.md |
| P2 | 11 | Frontend automated test coverage | Open, unscheduled | STATE.md |
| P2 | 12 | Card-identity case-sensitivity cleanup | Open, documented not fixed | STATE.md |
| P2 | 13 | Pagination for `/transactions` and listing endpoints | Open, no evidence yet needed | STATE.md |

P0 = the arc currently being built, in its locked build order (items 1
and 2 are built; 3 is next). P1 = the parser-tier roadmap, on hold while
P0 is in progress. P2 = named gaps with no scheduled arc.

Tier 1 parser work is not listed above because it is complete: all four
bank parsers are built and reconciling, per STATE.md "Current state" and
PRODUCT_VISION.md's sequencing steps 1 and 2.

## 7. Detailed Functional Requirements

### 7.1 Statement Parsing (built)
A personal credit card statement tracker, built session by session as a
deliberate, hands-on vehicle for learning Claude Code. It parses monthly
PDF credit card statements, persists parsed transactions to a local
SQLite database, and exposes that data through a queryable API and a web
dashboard.

Four bank/card-type parsers are implemented and reconciling against real
sample statements: HDFC Diners (across two known statement layouts, a
current template and an older "legacy" one, auto-detected from the PDF's
own text), ICICI Coral, SBI Titan, and IndusInd Legend. Every parser is
validated by the same reconciliation check — parsed totals against the
statement's own summary box.

The import pipeline works end-to-end and is bank-agnostic from the CLI
down: parsing, an adapter bridging parser output to storage
(`from_parsed_statement`, shared by all banks), atomic deduped writes, a
filtered read path, and `GET /transactions`, `GET /cards`,
`GET /statement-months`, and `GET /card-types` FastAPI endpoints. The
`statements` table carries a `statement_month` column (e.g. `July-2026`),
generated from `period_end` rather than typed in.

A single-page HTML frontend (`static/index.html`, served at `GET /`)
consumes all four endpoints via `fetch()`, rendering a transactions table
filterable by card, bank, card type, statement month, and date range
(from and to), with filter state synced to the URL.

Three command-line tools exist — `create_card`, `import_statement`, and
`query_transactions` — all following the same shape, each documented with
a usage docstring plus a README section.

*Sourcing:* adapted from STATE.md's "What this is" and "Current state",
both current as of Session 35.

### 7.2 Universal Parser Roadmap (P1)
The goal: any user can upload any bank's credit card statement and get
parsed, reconciled transactions — regardless of whether the app has seen
that bank's format before.

All tiers produce the same output (a `ParsedStatement` conforming to
`parsers/base.py`'s contract) and are validated by the same reconciliation
check (parsed totals vs. the statement's own summary box).

**Tier 1 — Pre-built parsers.** Hand-built, verified regex parsers for
known banks. Instant, free, offline, highest accuracy. All four planned
parsers are built and reconciling as of Session 35: HDFC Diners (two
layouts), ICICI Coral, SBI Titan, and IndusInd Legend.

**Tier 2 — Community-shared configs.** Users who have configured their
bank's format (via Tier 3 or Tier 4) can export and share their parser
config. Other users download it and import instantly — no setup needed.
Configs contain only regex patterns and field positions, never personal
data.

**Tier 3 — Guided manual config wizard.** A UI wizard that shows the user
their statement's raw text and walks them through identifying the format:
which part is the date, which is the amount, how are credits marked,
where is the summary box. One-time setup per bank format; the app caches
the config for all future imports. No LLM, no API key, no network
dependency.

**Tier 4 — LLM auto-learn.** For users with LLM API access. The app sends
extracted PDF text to an LLM (e.g., Claude API), which returns a
structured parser config — regex pattern, field positions, classification
rule, date format, summary extraction hints. The reconciliation check
validates the config automatically; if totals don't match, the app
retries or flags for manual review. On success, the config is cached —
first import is slow (LLM round-trip), every subsequent import is fast
and free (cached config, no LLM call).

**Why the current architecture supports this:**

- **`ParsedStatement` contract** — the output shape is identical regardless
  of which tier produced it. Storage, API, and frontend are parser-agnostic.
- **Reconciliation as a quality gate** — works for hand-built parsers and
  auto-generated configs equally. A parser that doesn't reconcile is
  flagged as wrong, regardless of how it was created.
- **Bank-agnostic infrastructure** — dispatch, adapter, CLI, and API are
  being generalized (Session 30+) so adding a new bank is "drop in a
  parser module," not "touch six files."
- **Hand-built parsers as training data** — the four Tier 1 parsers become
  few-shot examples for the Tier 4 LLM prompt, and reference
  implementations for Tier 3's wizard to emulate.

### 7.3 Expense Categorization & Analytics (P0)
Additive only. Reuses the existing parser pipeline, storage layer, and
`/transactions` API as-is. Adds label columns to the data model (as
built: nullable `category`, `subcategory`, `merchant` on `transactions`
— no separate categories table; the catalogs are the distinct values in
use), new endpoints for categorization and aggregation, and new frontend
screens alongside the existing transaction-list page.

**Module 1 — Upload & Auto-Import (built, Sessions 97–101).** An
Upload tab: drop or pick one PDF at a time. The bank is read off page 1
of the statement (a landmark per known bank; the card type is the
bank's one parser-backed type, since no sample names its card product
on the page) and resolved against the cards table — one card proceeds
silently, none offers an inline card-creation form pre-filled from the
detection, several are listed by nickname and last statement period
for the user to pick. A locked PDF that no `.env` password opens stops
with the bank and the key named; no partial parse. An unrecognised
format names the four known banks and offers two readers — a
bank-agnostic best-attempt parser (local, generic date/description/
amount rules) and an LLM-assisted parse (one call to the configured
Gemini model with the statement text, long digit runs redacted; no
format learned, nothing cached) — both landing on the same preview.
The preview shows period, count and a two-sided reconciliation of the
parsed debit and credit sums against the statement's own printed
totals; nothing is written until confirm, which is blocked on a
mismatch unless the user explicitly overrides, and blocked with no
override on a duplicate (same card, same period). Success stays on the
tab with a link to Review & Assign. Every step is a new entry point
onto the CLI's own parse → adapt → atomic-insert pipeline through one
shared bank registry, not a second pipeline.

**Module 2 — Categorization (built, Sessions 41–58).**

- Free-text categories only — no predefined starter list. Values are
  Title-Cased on write by one shared rule; `NULL` is the only "unset".
- Suggestion engines, all pattern-matching over the user's own past
  labels, no AI/LLM call: *category* — exact description match (majority
  vote, confidence = winning share) then most-similar description, global
  across cards; *subcategory* — exact match only, scoped to rows with the
  same category, falling back to the category name; *merchant* —
  category's exact-then-similar matching on the merchant field, global,
  falling back to the raw description. Fallbacks are shown in words, not
  as a percentage. One batch endpoint returns all three per transaction.
  Room to add an AI-based layer later if accuracy proves insufficient.
- Bulk categorization, as built: **manual multi-select of arbitrary
  transactions** (any category state, across groups) with a typed
  bulk-assign and separate per-field bulk-accepts for category and
  merchant (each applying every selected row's own displayed suggestion;
  merchant bulk excludes the raw-description fallback), plus a
  group-level "accept all" and a per-row change that can spread to the
  row's group. The originally-stated mechanism — "apply a category to
  every transaction from a given merchant in one action" — was not built
  as such: raw description text is the only merchant identity available
  and is not a reliable grouping key on its own. Grouping by suggested
  category and by description similarity fills that role.
- Review screen grouping modes: by suggested category (default) or by
  description similarity above a user-set percentage (anchor-based,
  non-transitive clustering; unmatched rows omitted with a visible
  count). Filters are a Bank → Card cascade plus month and date range,
  bidirectionally narrowed, URL-synced.
- Every write goes through one atomic assign endpoint taking
  per-field-optional entries; any unknown id rejects the whole request.

**Module 3 — Analytics Dashboard.**

- Spend by category, filterable by custom range, month, quarter, year.
  **Built (Sessions 65–69, 73–77), and grew well beyond this bullet's
  single-dimension scope** — recorded here the way Module 2's growth was:
  the aggregation returns a nested tree over any 2 or 3 of category /
  subcategory / merchant in the caller's chosen order (not category
  alone); it accepts independently combinable category / subcategory /
  merchant filters, "Uncategorized" selecting the unlabelled rows; the
  filter bar carries those three as a second row on every tab, in the same
  bidirectional-narrowing mesh as bank / card / month / dates; and the
  dashboard chart is a permutable three-level drill (Merchant / Category /
  Subcategory in any order, chosen with three level selects) in which
  clicking a bar sets the matching filter rather than keeping separate
  drill state. Refunds are netted, card payments excluded. Complete as of
  2026-09-13 (Session 77), pending the manual browser verification noted
  in STATE.md's open flags.
- Commentary is LLM-generated (e.g. a free-tier cloud API such as
  Gemini), not rule-based — a deliberate exception to the project's
  usual practice of never letting real financial data leave the machine.
  Scoped narrowly. **As originally scoped (Session 37):** only aggregated
  category totals (category, amount, period), never merchant names.
  **Reversed on 2026-09-13 (Session 73), deliberately:** once the
  dashboard's chart needed merchant-level grouping too, the payload was
  reconsidered and widened to carry the label names at all three levels
  — category, subcategory, and merchant — each with its net amount only,
  plus the period and total. Still never sent: raw transaction
  descriptions, individual transaction records, transaction counts,
  amounts other than the per-label aggregates, and reference numbers. The
  payload is built field by field from a fixed list, and a test guarantees
  nothing else can ride along.

**Build sequence:**

1. Categorization data model + suggestion engine (backend) — **done**
2. Categorization review/assign screen, including bulk-apply (frontend)
   — **done**, pending manual browser verification
3. Aggregation endpoint + dashboard with filters and LLM commentary —
   **done**, pending manual browser verification
4. Upload UI with auto-detect (Module 1) — **done** (Sessions 97–101),
   endpoints verified live once under an explicit exception; the tab
   itself pending manual browser verification

## 8. Non-Functional / Technical Constraints
- Single-user, local-file storage. Single-user is implicit throughout —
  no auth, no user table, one local SQLite file.
- Multi-row writes (a statement plus all its transactions) go through a
  single SQL transaction — no partial writes survive a failure.
- Reconciliation is a mandatory quality gate for every parser tier,
  including future ones: a parser that doesn't reconcile is flagged as
  wrong, regardless of how it was created.
- One parser module per bank + card type, with a dispatch layer routing
  by card type. Statement-layout detection is a separate, lower-level
  concern inside the bank module, not part of dispatch — the two axes
  are kept independent on purpose.
- Card identity: `nickname` must identify the physical card (e.g.
  `Primary`), never a statement period — the generated
  `statement_month` field is the correct place for that. Future imports
  should attach to the existing card, not create a new one per month.
- Multiple unnamed cards of the same bank/type are allowed on purpose;
  SQLite's NULL-distinct behavior for the `(bank, card_type, nickname)`
  UNIQUE constraint is preserved by design, not fixed.
- No index on `statements.statement_month` — an explicit decision, not an
  omission, given a single-user local-file database with a small
  statement count. Revisit only if that assumption stops holding.
- The frontend is a thin `fetch()`-based consumer of the API — it never
  reaches into the database directly, and never exposes anything the
  endpoints don't already return.
- Scripts under `scripts/` are run as `python3 -m scripts.<name>` from
  the project root with the virtual environment active, never invoked
  directly as a file path.

## 9. Data & Privacy Requirements
- When working with real financial data — imported bank statements,
  actual transactions in the database — only counts, reconciliation
  numbers, and statement period ranges may appear in any documentation
  surface. This includes DEVLOG entries, learning summaries, Claude Code
  prompts, README examples, screenshots, and chat transcripts shared for
  review. Never merchant names, never amounts, never individual
  transaction dates, never reference numbers, never reward point values.
- The rationale is that the DEVLOG and learning history are checked into
  git and may be shared publicly; real credit card statement content
  should never end up in a public git history — not the statement file
  itself (already git-ignored), and not fragments of it quoted into
  documentation either.
- Exploration output files (`data/exploration_output*.txt`) contain raw
  extracted text from real bank statements. They are git-ignored and must
  never be committed, pushed, or shared.
- **The one named exception:** dashboard commentary (Section 7.3) sends
  aggregated totals to an external LLM API: the period, the total, and
  the label names with net amounts at category, subcategory, and
  merchant level (widened from category-only on 2026-09-13, Session 73,
  a recorded reversal of the original scoping). Never raw transaction
  descriptions, individual transaction records, transaction counts, or
  reference numbers.

## 10. Assumptions & Open Questions
From PRODUCT_VISION.md (to be answered when that document is revisited):

- Config format: what schema describes a parser config portably (regex
  patterns, field positions, classification rules, date format)? — TBD
- Community registry: hosted service, GitHub repo of configs, or
  in-app sharing? — TBD
- Tier 3 wizard: what's the minimum viable UX that a non-technical user
  can complete? — TBD
- Tier 4 prompt engineering: how many few-shot examples are needed for
  reliable config generation? — TBD
- Reconciliation failure handling — **resolved for uploads (Session
  98)**: blocked by default with an explicit override; no retry,
  scoring, or queue

From EXPENSE_ANALYTICS_VISION.md (to be answered when each module is
scoped):

- Module 1: zero-match / multi-match card resolution at upload time —
  **resolved (Session 101)**: zero-match creates the card inline,
  multi-match picks from candidates by nickname + last statement period
- Module 3: Gemini API key storage — follows the existing `.env` secret
  convention (never in a Claude Code prompt) — TBD
- Module 3: behavior when the free-tier rate limit is hit — silent skip,
  cached last commentary, or a visible error state — TBD

## 11. Known Issues / Technical Debt
- Card identity has two known, unfixed asymmetries: `create_card`'s
  bank/card_type matching is case-sensitive, but bank dispatch is
  case-insensitive; and cards with a `NULL` nickname can silently
  accumulate duplicates, since SQLite treats each `NULL` as distinct.
- `list_cards()` orders by `created_at`; `list_cards_with_statements()`
  orders by `id` ASC instead. In practice these agree, since SQLite's
  `AUTOINCREMENT` id is assigned in insertion order, but it's a real (if
  inert) divergence between the two functions, not an accident.
- `list_card_types()` applies the same "only cards with a statement"
  filter as `list_cards_with_statements()` but lives in a different
  module and returns bank/card-type pairs rather than full card rows — a
  second, deliberate asymmetry.
- A `StarletteDeprecationWarning` (`httpx` with `starlette.testclient`)
  surfaced during Session 23's test run — unresolved, low-priority.
- The categorization frontend (Sessions 43–58) has not yet been seen
  rendered by Claude Code — verified by script parsing and code trace
  only; the manual browser walk is the outstanding gate (STATE.md open
  flags).
- The multi-select bar's "N selected" can include rows not currently on
  screen after a bulk accept or in similarity mode — deliberate, so the
  second bulk action can use the same selection; documented in STATE.md.

## 12. Revision History

| Version | Date | Change |
|---|---|---|
| 1.0 | 08 Sep 2026 | Initial consolidated PRD |
| 1.1 | 08 Sep 2026 | Sourced from reconciled STATE.md/PRODUCT_VISION.md; removed source-currency note and staleness entry |
| 1.2 | 12 Sep 2026 | Module 2 reconciled with what was built (Sessions 41–58): three labels, three suggestion engines, multi-select bulk actions in place of merchant-keyed bulk-apply, two grouping modes; requirements 1–2 marked built; verification gap recorded |
| 1.3 | 13 Sep 2026 | Commentary payload scope corrected: labels to merchant depth with amounts only (Session 73 reversal), in 7.3 and 9 |
| 1.4 | 13 Sep 2026 | Module 3 aggregation/dashboard marked built with its growth beyond scope (Sessions 73–77); requirement 3 status updated |
| 1.5 | 14 Sep 2026 | Module 1 upload marked built as scoped (Sessions 97–101): bank detection, card resolution, two-sided reconciliation gate, best-attempt and LLM readers; requirement 4 and the two Module 1 open questions updated |
