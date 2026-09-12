# Learning Summary — 12 Sep 2026

## What We Achieved
- A review screen for labelling transactions now exists: it groups them by the label the system suggests, lets the user accept a suggestion per row, per group, or across any ticked set, and offers a one-click list to pick or type a different label, optionally spreading it across a whole group.
- Every real sample statement on file — eighteen across four banks, 336 transactions — was loaded into the local database so that screen can be tried against real data; all eighteen still add up against the banks' own totals.
- The filter bar became a bank-then-card cascade in which every filter narrows the others to what actually has data, with two follow-up fixes: an "all banks" default that had wrongly locked the card list, and picking a card now setting its bank automatically.
- Labels are tidied automatically when saved so "food", "FOOD" and "Food" become one entry; the existing labelled rows were checked in one pass and already conformed.
- Transactions can also be grouped by how alike their descriptions look, at a similarity level the user chooses, with each row showing how closely it matches its group and groups still needing work listed first.
- Two further labels — a finer subcategory beneath the category, and a tidy merchant name — were added with their own suggestion logic, each shaped to its meaning and honest about when a suggestion is a real match versus a placeholder.
- Bulk acceptance was split into separate category and merchant actions, with the placeholder merchant suggestion excluded from bulk so one click can no longer stamp raw bank text across many rows; the bulk bar now stays on screen while scrolling.
- The look was refreshed, rows show whether money went out or came in, groups fold and unfold, and the project's overview documents were brought back in line with what was built — including a plain statement that none of the screen work has yet been seen running in a browser.

## How We Achieved It
- Every request was split into a backend step verified by the automated suite and a frontend step that only began once the suite was green; the suite grew from 267 to 361 passing over the day.
- Where a piece of logic was needed a second or third time — the similarity measure, the exact and fuzzy matching, the list-narrowing filters, the text-tidying rule — it was pulled into one shared piece rather than copied, and tests confirm the original behaviour did not move.
- Request and response formats were changed outright when they needed to grow, rather than keeping old and new side by side, and each such break was named as a break in the day's record.
- Wherever a suggestion is only a default rather than something learned, it is shown in words instead of a percentage, so a "100% sure" placeholder can never be mistaken for evidence.
- Because the screen could not be viewed from here, each front-end change was checked by parsing the code and tracing it by hand, and every record says "reasoned through, not seen" rather than claiming a verification that did not happen.
- Choices the briefs left open were decided explicitly and written down with reasons, including one deliberate bend of a stated rule and one place where a literal reading was flagged as possibly too eager — which the very next session confirmed and fixed.
- Real transaction content never appeared in any note, message, or commit; only counts and totals did.

## Key Learnings
1. **Tracing the code by hand catches real bugs — and is still not the same as seeing it run.** Reading the code alone found a screen whose buttons would all have stayed greyed out after the first save, a dropdown that would have been cut off at the table's edge, and a two-step action that would have lost its selection between steps. Each was fixed before it shipped, yet the day's records still say plainly that nothing was watched working, because the difference matters.
2. **A suggestion that always exists makes "accept all suggestions" dangerous.** Once the merchant suggestion fell back to the raw description whenever nothing better was known, a single bulk accept would have written raw bank text onto every ticked row. Splitting the action and keeping the placeholder out of bulk made the button do what its label says.
3. **An ambiguous phrase in a brief becomes a bug.** "Disabled until a bank is picked" was read as treating the "all banks" default as no pick at all, and the card list locked up. The fix was small, but the lesson is that defaults deserve a sentence of their own when the behaviour around them is specified.
4. **Simple grouping rules have consequences worth writing down.** Grouping look-alike descriptions by comparing each against the first one in its group is easy to explain, but it means the result can depend on the order the rows arrive in. Naming that as a property, and testing it, stops it from being reported later as a defect.
5. **Overview documents drift fastest on the busiest days.** After twenty sessions the plan still described a bulk-labelling mechanism that was never built and a single label where three now exist. Reconciling them from the day-by-day record — not from memory — and adding a rule that every session's summary states its own number keeps the record and the conversation that plans from it in step.
