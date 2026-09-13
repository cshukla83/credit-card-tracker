# Product Vision — Expense Categorization & Analytics

Parallel arc to docs/PRODUCT_VISION.md (parser tiers), chosen ahead of the
Tier 2/3/4 parser decision. Captured during Session 37 planning.

## The goal

Turn stored, parsed transactions into spend insight: categorize every
transaction, and surface where money is going and where it can be curbed
— filterable by date range, month, quarter, or year.

## Relationship to the existing system

Additive only. Reuses the existing parser pipeline, storage layer, and
`/transactions` API as-is. Adds label columns to the data model (as
built: `category`, `subcategory`, `merchant` on `transactions` — no
separate categories table), new endpoints for categorization and
aggregation, and new frontend screens alongside the existing
transaction-list page.

## Modules

### Module 1 — Upload & Auto-Import
Drag-and-drop upload that auto-detects the bank/card from the PDF and
loads it — no manual card selection. This reverses the STATE.md decision
that card-type auto-detection is deferred; that reversal is the locked
decision as of this document. Zero-match (new card) and multi-match
(ambiguous existing card) handling are deliberately left open — to be
resolved when this module is actually scoped, per the project's
anti-speculation rule, since it's last in the build sequence.

### Module 2 — Categorization
Built in Sessions 41–58 (build-sequence steps 1 and 2); the bullets below
describe what was built, with the original intent noted where it changed.

- Free-text categories only — no predefined starter list. The catalogs
  the UI offers are simply the distinct values already in use.
- Suggestion engine: simple pattern-matching learned from the user's own
  past categorizations — an exact description match first, then the most
  similar description — global across all cards. No AI/LLM call for
  suggestions. Room to add an AI-based layer later if accuracy proves
  insufficient.
- Bulk categorization is in scope, and was built as **manual multi-select
  of arbitrary transactions** (any category state, across group
  boundaries) with two kinds of bulk action: *typed bulk-assign* (one
  value to every selected row) and *per-field bulk-accept* — "accept
  category suggestions" and "accept merchant suggestions" as separate
  actions, each applying every selected row's own displayed suggestion
  for that one field. Group-level "accept all" covers the common
  same-suggestion case. The original idea — "apply a category to every
  transaction from a given merchant in one action" — was dropped as the
  mechanism, because the raw, unnormalized description text is the only
  merchant identity the statements provide, and it is not a reliable
  grouping key on its own (case, suffixes, reference numbers vary within
  one merchant). Grouping by *suggested* category and by *description
  similarity* (below) fills that role instead.
- **Grew beyond original scope: three labels, not one.** `subcategory`
  and `merchant` are distinct fields alongside `category`, each nullable,
  each with its own suggestion logic shaped to its meaning — subcategory
  suggests only from rows with the same category and an identical
  description, falling back to the category name; merchant reuses
  category's exact-then-similar matching and falls back to the raw
  description when nothing has been learned. Fallbacks are labelled in
  words, never as a confidence percentage.
- **Grew beyond original scope: two grouping modes on the review
  screen.** *Group by suggested category* (the default) clusters rows by
  what the engine proposes; *group by similarity* clusters rows whose
  descriptions resemble each other above a user-set percentage,
  regardless of category state, so look-alike transactions can be handled
  together even before any suggestion exists. Rows below the threshold
  are not shown in that mode, with a count making that explicit.

### Module 3 — Analytics Dashboard
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

## Why the current architecture supports this

- The `ParsedStatement` → storage pipeline is untouched; categorization
  and analytics are a new layer on top, not a rework.
- The existing filter/URL-state pattern from the transactions page
  extends naturally to the dashboard's date-range filters.

## Build sequence

1. ~~Categorization data model + suggestion engine (backend)~~ —
   **complete** (Sessions 41–42, extended in 49–50, 53, 55).
2. ~~Categorization review/assign screen, including bulk-apply
   (frontend)~~ — **complete** (Sessions 43–48, 51–52, 54, 56–58);
   API-tested, awaiting the manual browser walk recorded in STATE.md's
   open flags.
3. ~~Aggregation endpoint + dashboard with filters and LLM commentary~~ —
   **complete** (Sessions 65–69, 73–77), pending the manual browser
   verification recorded in STATE.md's open flags.
4. Upload UI with auto-detect (Module 1)

## Open questions (to be answered when each module is scoped)

- Module 1: zero-match / multi-match card resolution at upload time
- Module 3: Gemini API key storage — follows the existing `.env` secret
  convention (never in a Claude Code prompt)
- Module 3: behavior when the free-tier rate limit is hit — silent skip,
  cached last commentary, or a visible error state
