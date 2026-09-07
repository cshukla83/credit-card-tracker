# Learning Summary — 07 Sep 2026

## What We Achieved
- The system can now read statements from four different banks, up from two at the start of the day.
- The third bank's reader was completed and then proven against all four of its real statements, where previously only one of those checks was written down as a permanent test.
- The fourth bank went from never having been examined to fully working within the same day, and every one of its four statements adds up exactly against the totals the bank itself prints.
- Across both banks worked on today, every purchase total and every payment total matched the printed figure to the last paisa — sixteen separate sums, none merely close.
- The automated checks that run on every change grew from 186 to 239, with no existing check broken along the way.
- Adding the fourth bank required one new folder for its reader plus a single line in the list of supported banks — nothing else in the system had to change.

## How We Achieved It
- Each new bank was studied first and built second, with the findings written down in general terms so the build stage never needed to reopen a real financial file.
- A written note from an earlier study was checked against the actual document rather than trusted, and turned out to describe a different field than the one needed — catching that before writing any code avoided a failure that would have produced no error at all, just a missing date range.
- The fourth bank's study deliberately went looking for traps before any code existed, and found the one that mattered: figures printed down the side of the page get glued onto the end of transaction lines when the page is read as text.
- That trap was designed around rather than cleaned up after, so the reader takes the first amount on a line and ignores anything trailing it.
- Where a rule could fail either loudly or quietly, the loud option was chosen every time — an unfamiliar transaction code stops the import rather than being guessed at or silently dropped.
- Claims about tests actually testing something were checked rather than assumed: for the statements that run onto a second page, the transactions on that second page were counted to confirm the check would genuinely catch a reader that stopped after page one.
- Known limitations were written down plainly rather than left implied — including one place where the parser cannot see a distinction the statement makes visually, named as the first thing to investigate if the numbers ever stop matching.
- Two figures on the fourth bank's statement were deliberately left unread, because their position on the page had no reliable relationship to their labels and nothing needed them.

## Key Learnings
1. **A stricter-looking rule can be the more dangerous one.** The obvious way to recognise the fourth bank's transaction lines was to accept only the two markers it actually uses. That version would have quietly discarded any line using a third marker, with no error — so the rule was deliberately loosened to accept any marker and then check it separately, turning a silent omission into a loud stop.
2. **Exploring first is what makes building uneventful.** The fourth bank's reader worked on the first attempt, but not because it was easy or especially carefully written. The one pattern that would have broken it was found in the day's earlier study and designed around in advance; written the obvious way, three of its four statements would each have lost two purchases and failed to add up.
3. **Written notes are evidence, not fact.** A finding recorded during an earlier study was accurate about one part of the document and wrong about the part that mattered. Re-checking it against the real file took minutes; trusting it would have produced a reader that silently returned no date range at all.
4. **"It worked when I checked" is not the same as "it is checked".** The third bank's reader had already been confirmed against all four of its statements, but only one of those confirmations existed as a permanent test. Turning the other three into real tests found no problems — the gap being closed was that the knowledge would have been forgotten, not that the code was wrong.
5. **Exact agreement is much stronger evidence than close agreement.** Every total today matched the bank's printed figure precisely rather than within a tolerance. A reader that dropped a row or counted one twice would land near the right number sometimes, but landing dead-on sixteen times in a row does not happen by accident.
6. **Passing tests deserve the same scepticism as failing ones.** Rather than assume that covering more statements covered the harder cases, the statements whose transactions continue onto a second page were identified and their second-page transactions counted — confirming those tests would actually notice a reader that stopped early, instead of passing for uninteresting reasons.
