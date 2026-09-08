# Product Vision — Expense Categorization & Analytics

Parallel arc to docs/PRODUCT_VISION.md (parser tiers), chosen ahead of the
Tier 2/3/4 parser decision. Captured during Session 37 planning.

## The goal

Turn stored, parsed transactions into spend insight: categorize every
transaction, and surface where money is going and where it can be curbed
— filterable by date range, month, quarter, or year.

## Relationship to the existing system

Additive only. Reuses the existing parser pipeline, storage layer, and
`/transactions` API as-is. Adds a `categories` concept to the data model,
new endpoints for categorization and aggregation, and new frontend
screens alongside the existing transaction-list page.

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
- Free-text categories only — no predefined starter list.
- Suggestion engine: simple pattern-matching learned from the user's own
  past categorizations. No AI/LLM call for suggestions. Room to add an
  AI-based layer later if accuracy proves insufficient.
- Bulk categorization is in scope: applying a category to every
  transaction from a given merchant in one action, not row by row —
  without this, the "learns over time" benefit doesn't get exercised
  fast enough to matter.

### Module 3 — Analytics Dashboard
- Spend by category, filterable by custom range, month, quarter, year.
- Commentary is LLM-generated (e.g. a free-tier cloud API such as
  Gemini), not rule-based — a deliberate exception to the project's
  usual practice of never letting real financial data leave the machine.
  Scoped narrowly: only aggregated category totals (category, amount,
  period) are sent to the API — never individual transactions, merchant
  names, or reference numbers.

## Why the current architecture supports this

- The `ParsedStatement` → storage pipeline is untouched; categorization
  and analytics are a new layer on top, not a rework.
- The existing filter/URL-state pattern from the transactions page
  extends naturally to the dashboard's date-range filters.

## Build sequence

1. Categorization data model + suggestion engine (backend)
2. Categorization review/assign screen, including bulk-apply (frontend)
3. Aggregation endpoint + dashboard with filters and LLM commentary
4. Upload UI with auto-detect (Module 1)

## Open questions (to be answered when each module is scoped)

- Module 1: zero-match / multi-match card resolution at upload time
- Module 3: Gemini API key storage — follows the existing `.env` secret
  convention (never in a Claude Code prompt)
- Module 3: behavior when the free-tier rate limit is hit — silent skip,
  cached last commentary, or a visible error state
