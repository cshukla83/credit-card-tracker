# Learning Summary — 29 Aug 2026

## What We Achieved
- A second bank's statements can now be read by the system: today took that format from "never examined" to fully working, in a single day.
- The new reader was proven correct against four separate real statements, with every purchase total and every payment total matching the totals the bank itself printed on each statement.
- The command that loads a statement into the system now works for both banks, where before it could only ever use the first one — the second bank's reader existed but was unreachable.
- Adding a third bank in future now takes one small entry in a single list, rather than changes scattered across several parts of the system.
- The part that translates a read statement into stored records turned out to already work for any bank without modification, which was confirmed by checking rather than assumed.

## How We Achieved It
- The day was deliberately split into stages — first understand the document, then build, then stress-test, then connect it up — so that each stage's work rested on findings already written down rather than on guesses.
- The document was studied once, thoroughly, and the findings written down in a general form, so later stages never needed to reopen the real financial file.
- A trap in the automated document-reading tools was spotted during that study: for this bank's layout the tools appeared to work while silently returning only a fraction of the real transactions, which steered the whole build away from an approach that would have quietly lost data.
- Rather than trusting that the new reader worked because its own tests passed, it was pointed at three further real statements it had never seen — the same exercise that, for the first bank, had previously exposed two genuine defects.
- When those three all matched perfectly, that success was itself double-checked with an independent count, to rule out the possibility of one missed transaction and one wrongly-included one cancelling each other out in the totals.
- Before renaming the piece that stores statements, its actual behaviour was inspected to find out whether it was genuinely tied to the first bank or only named as though it were — it was only named that way.
- New automated checks were verified to be actually running rather than quietly skipping themselves, since they are designed to stand aside when the sample files are unavailable and would otherwise have reported success while testing nothing.
- A missing check was named openly instead of faked: the second bank has only one known statement layout, so the layout-detection check that exists for the first bank has no counterpart, and the reason was recorded alongside the tests.

## Key Learnings
1. **A tool that fails loudly is safer than one that fails quietly.** The automated table-reading tools handled this bank's busiest page by returning a single transaction and omitting the rest, which looks like success. Code that only asked "did anything come back?" would have shipped while losing most of a statement.
2. **Designing away a problem beats cleaning up after it.** Decorative chart text in the source document sometimes lands on the same line as a real transaction. Instead of adding a step to strip that noise, the matching rule was written to care only about how a line ends — so the noise is ignored automatically and lines containing nothing real still produce nothing.
3. **Removing judgement calls removes the chance to get them wrong.** The first bank's reader has to infer which entries are refunds using keywords and fallback rules, and that inference is exactly where its past defects were found. This bank prints an explicit marker on every refund, so the new reader reads the marker instead of guessing — and it survived three unseen statements without a single correction.
4. **Two independent checks agreeing is much stronger evidence than either alone.** Matching totals proves the amounts are right; counting transaction lines proves the right set of entries is being added up. Together they rule out errors that would cancel out and pass a totals-only check.
5. **Assumed coupling is often just an inherited name.** A component named after the first bank looked like it would need real work to support a second. Inspecting it showed it had never depended on anything bank-specific — it needed a more accurate name and nothing else, and the old name had been overstating the work for some time.
6. **A test that skips itself is indistinguishable from a test that passes, unless you look.** Today's new checks stand aside when the sample statements aren't present, so a clean result could have meant everything reconciled or that nothing ran at all. Confirming which one it was took a separate deliberate step.
