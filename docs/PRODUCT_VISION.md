# Product Vision — Universal Statement Parser

> **Status:** the Tier 2/3/4 decision below is on hold. Session 36
> started a parallel arc — expense categorization and analytics — see
> `docs/EXPENSE_ANALYTICS_VISION.md`. This document resumes once that
> arc is done.

Strategic direction for the credit card statement tracker, captured during
Session 29–30 planning. To be revisited once the four known bank parsers
and the infrastructure generalization arc are complete.

## The goal

Any user can upload any bank's credit card statement and get parsed,
reconciled transactions — regardless of whether the app has seen that
bank's format before.

## Parser tiers

All tiers produce the same output (a `ParsedStatement` conforming to
`parsers/base.py`'s contract) and are validated by the same reconciliation
check (parsed totals vs. the statement's own summary box).

### Tier 1 — Pre-built parsers
Hand-built, verified regex parsers for known banks. Instant, free,
offline, highest accuracy. Current coverage: HDFC Diners, ICICI Coral.
Planned: SBI, IndusInd.

### Tier 2 — Community-shared configs
Users who have configured their bank's format (via Tier 3 or Tier 4) can
export and share their parser config. Other users download it and import
instantly — no setup needed. Configs contain only regex patterns and field
positions, never personal data.

### Tier 3 — Guided manual config wizard
A UI wizard that shows the user their statement's raw text and walks them
through identifying the format: which part is the date, which is the
amount, how are credits marked, where is the summary box. One-time setup
per bank format; the app caches the config for all future imports. No LLM,
no API key, no network dependency.

### Tier 4 — LLM auto-learn
For users with LLM API access. The app sends extracted PDF text to an LLM
(e.g., Claude API), which returns a structured parser config — regex
pattern, field positions, classification rule, date format, summary
extraction hints. The reconciliation check validates the config
automatically; if totals don't match, the app retries or flags for manual
review. On success, the config is cached — first import is slow (LLM
round-trip), every subsequent import is fast and free (cached config,
no LLM call).

## Why the current architecture supports this

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

## Sequencing

1. Finish four known bank parsers (HDFC ✓, ICICI ✓, SBI, IndusInd)
2. Generalize infrastructure (bank-agnostic dispatch, adapter, CLI)
3. Revisit this document and pick the next tier to build

## Open questions (to be answered when this is revisited)

- Config format: what schema describes a parser config portably (regex
  patterns, field positions, classification rules, date format)?
- Community registry: hosted service, GitHub repo of configs, or
  in-app sharing?
- Tier 3 wizard: what's the minimum viable UX that a non-technical user
  can complete?
- Tier 4 prompt engineering: how many few-shot examples are needed for
  reliable config generation?
- Reconciliation failure handling: retry logic, confidence scoring, or
  manual review queue?
