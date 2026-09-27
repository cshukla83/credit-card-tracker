# Learning Summary — 16 Aug 2026

## What We Achieved
- Built the full storage layer: a SQLite schema (`cards`, `statements`, `transactions`, with foreign keys and dedup constraints), a connection helper, and an atomic write path.
- Refactored the schema so a "card" (bank + card type + optional nickname) is the real anchor point, with statements linked to a card rather than storing a free-text bank name.
- Restructured the HDFC parser into a dispatch layer that routes by card type, laying the groundwork for supporting more card types and banks later without reworking what already exists.
- Extended the parser to surface each statement's billing period, not just its list of transactions.
- Built the bridge connecting parsing to storage — an adapter, a command-line import script, and end-to-end tests — the first point where real statement data flowed through the complete pipeline, from PDF to database.

## How We Achieved It
- Worked in small, focused sessions, each with a narrow goal and its own test coverage, rather than one large sweeping change.
- Used one consistent rule to decide when to add work beyond what was explicitly asked: *does the code make a promise that no test currently checks?* This caught a missing cascade-delete test, a renamed module's stale caller, and a missing check on the new billing-period data — each a real gap, not scope creep.
- Verified uncertain library behavior empirically before depending on it, rather than assuming: confirmed exactly how a failed database write rolls back, how to tell two different error types apart, and — before writing any parsing logic — confirmed with real statement data that a billing period could actually be derived the way we planned to derive it.
- Kept a running "Invariants" note in the project log, so decisions made early (such as never caching a database connection or path) can't get silently broken by later work.
- Verified the finished pipeline three separate ways — automated unit tests, automated tests against real statements, and a manual command-line run — rather than trusting any single check alone.

## Key Learnings
1. **Small, sequential steps make large changes safer.** Each session was independently testable, so mistakes surfaced immediately instead of compounding across unrelated work.
2. **When a library's behavior is ambiguous, verify it before relying on it.** A quick, throwaway check settles the question with certainty instead of a guess baked into production code.
3. **"Filling a gap" and "scope creep" are different things**, and the difference is testable: if the code makes a promise nothing currently verifies, that's a real gap worth closing.
4. **Renaming or restructuring code demands an exhaustive search for every caller** — not just the obvious ones. An unmentioned caller can still break silently if it's missed.
5. **Automated tests don't replace running the real thing.** A manual end-to-end check is cheap insurance against blind spots the test suite doesn't know it has.
