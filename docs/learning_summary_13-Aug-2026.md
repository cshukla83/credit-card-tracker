# Learning Summary — 13 Aug 2026

## What We Achieved
- Built a working parser that extracts structured transactions (date, description, amount, debit/credit, reward points) from password-protected HDFC credit card statement PDFs.
- Extended the parser to support **two different HDFC statement layouts** — a current template and an older ("legacy") one — with automatic detection of which layout a given statement uses.
- Verified the parser against **six real statements**, finding and fixing three real bugs along the way.
- Added an automated test suite (38 tests) covering both parsers' logic, plus integration checks against all six real statements.

## How We Achieved It
- Started by exploring a sample PDF's raw text structure, since `pdfplumber`'s built-in table extraction didn't cleanly separate transaction fields on this layout. Used the patterns found there to design a regex-based line parser.
- Used **reconciliation** — comparing the sum of parsed transactions against the totals the statement itself declares — as the main way to catch parsing errors, without needing to manually inspect every row of real financial data.
- Whenever reconciliation failed, followed a consistent diagnostic routine: check for unmatched lines, check for missed lines, verify the summary box's field order, compare debit/credit gaps, then isolate the specific broken transaction.
- When a genuinely different statement layout appeared, added a second parser plus an auto-detecting dispatcher, rather than forcing one regex to cover both formats.
- Refactored the code to separate pure text-parsing logic from PDF/password handling, enabling fast unit tests on fabricated example data, plus a smaller set of integration tests against the real statement files (which skip safely if the files or password aren't present).

## Key Learnings
1. **Real-world documents rarely follow one fixed format.** The bank changed its statement layout at some point; the parser needed to detect and handle both versions rather than assume one.
2. **Reconciliation is a powerful, low-effort correctness check.** Comparing computed totals against a document's own declared totals catches subtle parsing bugs without manual row-by-row review.
3. **Keyword matching is risky with concatenated text.** Merchant and city names sometimes run together with no space (e.g. "PAYMENTSBANGALORE"), so plain substring matching on words like "PAYMENT" can misfire — word-boundary matching is safer.
4. **Structural markers beat keyword guessing when available.** An explicit suffix (like "Cr" for credits) is a more reliable signal than inferring meaning from surrounding text.
5. **Sensitive data doesn't need to be part of testing.** Separating "pure logic" from "file and password handling" made it possible to test the parsing logic safely with fabricated data, while still verifying correctness against the real statements through a small, gated set of integration tests.
