# Learning Summary — 20 Aug 2026

## What We Achieved
- Made the stored transaction data actually retrievable: you can now ask "show me transactions on this card between these two dates" and get an answer back, both from the code and from a simple command-line tool.
- Gave card creation its own proper command-line tool, replacing the ad-hoc one-liner that had been in use until now.
- Documented — in the project's own files — how to actually run the command-line tools, so this doesn't get rediscovered the hard way each time.
- Verified the full pipeline against a real statement end-to-end: imported a real HDFC statement into a fresh database and confirmed that querying it back produced the right count of transactions in the right order, with date filters and boundary dates behaving correctly.

## How We Achieved It
- Built the read side in two focused steps: first the underlying function that fetches transactions with optional filters (card, start date, end date), then a thin command-line wrapper over it. Kept the underlying function flexible — one function with optional filters — rather than creating separate helpers for "by month," "by week," etc. Fewer moving parts, more ways to combine them.
- Chose both date boundaries to be inclusive (a transaction on the start date and one on the end date are both included), because the tool is meant for humans, not for chaining into other machines.
- Extracted a shared helper the moment it had a second caller — not before. Small, disciplined refactor exactly when the need appeared.
- Ran the finished tool against a real statement and reported only counts and behavior back into the working log, never actual amounts, merchants, or dates — the same discipline that has kept real financial data out of the project's history from day one.
- When the command-line tool failed on first run with an unhelpful Python error, treated it as a signal that the project had an undocumented convention (how to invoke the tools) and closed that gap by adding usage notes to every tool and a section in the README — so the next person, or the next session, doesn't hit the same wall.
- Surfaced and documented two subtle "gotchas" in how cards are identified — one about capitalization, one about unnamed cards — that weren't bugs but were the kind of thing that would surprise someone months later. Named them explicitly in the project log so a future design decision can address both together, rather than patching one and forgetting the other.

## Key Learnings
1. **The point of infrastructure is that you can finally use it.** Twenty-plus sessions of parsing, storing, and testing built a solid foundation, but until the read side existed, none of it was accessible. The moment the retrieval function landed, the whole project became something you could actually query, not just feed.
2. **A confusing error on first use is usually a documentation gap, not a code bug.** The tools worked correctly — the missing piece was that nothing in the project explained how to invoke them. Fixing the documentation prevents the same rediscovery next time.
3. **Automated tests can pass while a user-facing bug hides in plain sight.** The tests exercised the underlying functions directly, so they never hit the invocation problem the command-line tool had. Manual end-to-end verification remains the only reliable catch for this category of issue.
4. **Surprises worth naming are worth writing down immediately.** Two quirks about how cards are identified surfaced during verification. Neither was a bug — both were consequences of earlier decisions — but writing them into the log while the context was fresh means a future design session inherits both, together, instead of one being forgotten.
5. **"Ship something the user can see" is a real product argument, not just a slogan.** Recognizing that the next arc — building a browser view of transactions — is where the project stops being infrastructure and starts being a tracker changed the shape of what comes next.
