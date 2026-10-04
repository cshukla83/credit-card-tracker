# Release Notes

A record of every new feature, enhancement and fix in Credit Card Statement
Tracker, newest first. Add an entry with each change that affects what the
app does or how it is used. Internal refactors and test-only changes are
not listed.

Entries before 2026-10-04 were reconstructed from the commit history.

Each entry uses these headings as needed:

- **Added**: new features
- **Changed**: changes to existing behaviour
- **Fixed**: bug fixes
- **Docs**: user-facing documentation (the user guide carries its own
  version number, shown here when it changes)

---

## 2026-10-04

### Added
- **Drill-down transactions list on the Dashboard.** Clicking into the
  chart, or setting a Category, Subcategory or Merchant filter, shows the
  individual transactions behind the current drill path below the
  breakdown table. It shows 25 per page with Prev / Next and a
  "Showing X–Y of N" label, and returns to page 1 whenever the drill path,
  period or filters change. Purchases, refunds and card payments are all
  listed; credits show as negative amounts.
- `GET /transactions` accepts an optional `page` parameter. With it, the
  response is `{transactions, total, page, page_size}`; without it, the
  response is the same plain list as before.

### Docs
- User guide **1.2**: new Section 8.4 Transactions List; AI Commentary
  moved to 8.5; version history table added.
- User guide **1.1**: corrected against current behaviour: what the AI
  commentary sends, how the inline editor saves and cancels, section
  cross-references, the non-existent "Verified" status, payment flag
  values, suggestion tiers, bulk-accept buttons and period controls.
- README and SECURITY.md: AI commentary sends category, subcategory and
  merchant names with amounts; passwords come from `.env`; commentary runs
  only on request; the totals check replaces the "Verification workflow"
  description.

## 2026-09-27

### Added
- User guide **1.0** (`docs/USER_GUIDE.docx`).
- MIT licence, `SECURITY.md` and `.env.example`.

### Changed
- PDF files are ignored by git, so statements can never be committed.

## 2026-09-15

### Changed
- AI-assisted import is a sliding toggle, and its helper text says what
  data leaves your machine.
- The Unrecognized Statement screen is redesigned into a single flow.
- When the totals do not reconcile, the preview shows every row and states
  the counts behind the gap.
- New **Unverified** totals status for statements whose printed totals
  could not be found.
- A failed AI-assisted parse explains what happened in plain words.

### Fixed
- The AI-assisted parser asks for the statement's grand totals rather
  than only purchases.

## 2026-09-14

### Added
- **Upload tab**: drop a statement PDF; the app detects the bank and card,
  previews the extracted transactions, checks them against the statement's
  printed totals, and imports on confirmation.
- Row-level preview popup; import controls appear after the preview.
- Best-effort parser for banks without a dedicated parser, and optional
  AI-assisted parsing (Google Gemini).
- "Password needed" screen with Retry and Upload another file.
- Cards entered during an upload are created only when the import is
  confirmed.

### Changed
- Unlocking a PDF tries every `*_SAMPLE_PASSWORD` set in `.env`.
- Upload is the first tab.
- Shorter, clearer messages for duplicate statements, multiple files and
  missing passwords.
- The card-payment column sits next to the type column on both review
  tables.

### Fixed
- Ticking a checkbox no longer resets the scroll position.

## 2026-09-13

### Added
- **Reviewed tab**: every fully labelled transaction in a sortable table,
  editable in place.
- **Inline label editor**: click a Category, Subcategory or Merchant cell
  to edit it, with a dropdown of existing values and arrow-key navigation.
- Sortable columns on All Transactions.
- Category / Subcategory / Merchant filters on every tab.
- **Three-level dashboard drill-down** in any order (Merchant, Category,
  Subcategory), with a breadcrumb to step back.
- Subcategory suggestions learned from the same merchant and category.
- Bulk accept for subcategory suggestions.

### Changed
- Review & Assign shows only transactions that still need a label.
- Credit rows (refunds and payments) cannot be bulk-selected.
- The subcategory editor is available only once a category is set.

## 2026-09-12

### Added
- **Dashboard tab**: spend by category over a chosen period, with
  drill-down and an on-demand AI commentary ("Generate insight").
- **Card payment flag**: payments are detected at import, can be marked
  or unmarked on Review & Assign, and are left out of spend totals.
- Subcategory and Merchant labels with learned suggestions.
- Bulk accept of suggestions and a typeahead to label many rows at once.
- "Group by similarity" mode on Review & Assign.
- **Review & Assign tab** for categorising transactions.

### Changed
- Bank and Card pickers narrow each other; picking a card sets its bank.
- Labels are stored in Title Case.
- Visual refresh: type pills, collapsible groups, row hover.

## 2026-09-11

### Added
- Transaction categories with learned suggestions.

## 2026-09-07

### Added
- SBI Titan and IndusInd Legend statement parsers.

## 2026-08-29

### Added
- ICICI Coral statement parser.

### Changed
- One registry dispatches statements to the right bank parser.

## 2026-08-25

### Added
- Filter transactions by card, date range, statement month, bank and card
  type; card picker and date range on the transactions page.

## 2026-08-23

### Added
- First web page listing transactions.

## 2026-08-21

### Added
- `GET /transactions` API.

## 2026-08-20

### Added
- Command-line tools to create cards and query transactions.

## 2026-08-16

### Added
- Local SQLite storage with duplicate-safe imports, cards, and a
  command-line statement import.

## 2026-08-13

### Added
- HDFC Diners statement parser, covering both the current and the older
  statement layout.

## 2026-08-10

### Added
- Project scaffold (FastAPI); statement passwords loaded from `.env`.
