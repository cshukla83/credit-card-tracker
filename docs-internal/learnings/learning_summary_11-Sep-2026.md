# Learning Summary — 11 Sep 2026

## What We Achieved
- A fresh, verified description of how the database is laid out now exists, written straight from the code that creates the tables and cross-checked by asking a scratch copy of the database what it had actually built.
- That check surfaced facts no earlier record had noticed: two indexes the code never asks for exist because the database adds them to enforce uniqueness, and the transactions table has no index at all — recorded as observed, not as a decision anyone made.
- The question of where the merchant name lives was settled: one column holds exactly what the statement said, with nothing cleaned up, so any future grouping by merchant will have to do that cleaning itself.
- Each transaction can now be labelled with a spending category, and the system can suggest a label for an unlabelled one by looking at what the user labelled before — an identical description first, otherwise the most similar one, always with a score for how sure it is.
- Labels can be applied to one transaction or many in a single request that either applies to all of them or to none; an existing database is upgraded in place, and 28 new checks bring the automated suite to 267 passing.

## How We Achieved It
- The status documents were deliberately not used as a source for database facts, because they had drifted before; the code and the database engine's own answers were.
- Claims were tested empirically rather than transcribed — including one draft sentence about what the database engine forbids, which a one-line experiment showed to be wrong, so the document was corrected before it was finished.
- Where no decision had been recorded for something, the document said "observed, not decided" rather than inventing a rationale after the fact.
- One part of the specification could not be delivered as written — breaking ties by the most recently applied label, because no timestamp is stored — so the closest available stand-in was used, and that substitution was flagged before building and written down everywhere it matters.
- Choices the brief left open, such as how confident to report a contested match, were decided explicitly and justified in writing rather than left implicit in the code.
- No real database was opened and no real transaction data appeared in any document; the one example value given is a pattern, not a real one.

## Key Learnings
1. **Ask the system what it built, don't just read what you asked it to build.** Reading the table definitions alone would have said "no indexes"; asking the database engine showed two, created automatically. "No explicit index" and "no index" are different claims, and only the experiment told them apart.
2. **When a requirement cannot be met as stated, substitute openly.** The tie-break rule asked for something the data cannot support. Using a stand-in silently would have looked like compliance; naming it as a stand-in in the code, the data documentation, and a test keeps the gap visible for whoever later decides whether it matters.
3. **A recorded non-decision is more useful than an invented reason.** Two missing indexes had never been discussed. Writing them down as unexamined, rather than dressing them up as deliberate, leaves an honest to-do instead of a false sense of closure.
4. **Report a contested answer as contested.** When past labels for the same merchant disagree, the suggestion says how strongly they agreed instead of claiming full confidence. A default of "100% sure" would have hidden exactly the cases where the user most needs to look.
