# Learning Summary — 25 Aug 2026

## What We Achieved
- Every statement now automatically carries its own month label, computed from the dates already on file, instead of that information depending on someone typing it into the wrong place.
- The transactions page can now be narrowed down by which month a statement covers and by which bank and card type it belongs to, on top of the filters already available, all working together and all reflected in the page's shareable address.
- A bug that had been quietly present since the very first version of the page-serving system was found and fixed, so requests no longer risk failing partway through — sometimes without any visible sign that anything had gone wrong.

## How We Achieved It
- Before writing any of today's database changes, small standalone experiments were run first to check exactly how the database would actually behave, rather than assuming a plausible-sounding answer was correct.
- One of those experiments used a more realistic setup — checking behavior against data that already existed, not an empty starting point — and got a different, more accurate answer than a simpler first check had given.
- A related check meant to detect whether a piece of setup had already been done was found to always give the wrong answer for this particular kind of field, and was replaced with one that was tested directly and confirmed to actually work.
- Hands-on testing of the real, running page surfaced a separate, older problem that the automated checks had never been able to reach, by reading through the system's own operational logs rather than only checking whether the visible result looked correct.
- The database-connection fix was scoped narrowly to the exact safety condition it needed to relax, with the reasoning for why that was safe written down alongside the fix, and confirmed with the same experiment-first approach used earlier in the day.
- A real gap was named rather than papered over: today's connection fix wasn't backed by an automated test, because the current testing setup structurally cannot reach the situation that caused the bug — and that limitation was written down openly instead of adding a test that would look like coverage without actually being coverage.

## Key Learnings
1. **Checking a plausible answer against a more realistic scenario changed the outcome, three separate times today.** A storage setting behaved differently depending on whether existing data was already present. A check for whether a setup step had already run turned out to always give the wrong answer for one kind of field. And a real bug in how the system handles requests only became visible by reading through operational logs during hands-on use, not by trusting that a correct-looking result meant everything underneath had worked. The common thread: a quick first answer looked fine each time, and each time a more thorough check found it wasn't.
2. **A correct-looking result can still hide a failure happening right behind it.** One of today's bugs let a request return the right answer to the user while quietly failing during its own cleanup step immediately afterward — invisible unless someone went looking at what happened after the visible part finished.
3. **Automated checks have real, structural blind spots.** The testing tools in place today run everything in a simplified way that could never have caught the request-handling bug, no matter how many tests were written — only hands-on use of the real, running system caught it.
4. **Naming a gap honestly beats faking coverage.** No test was added for today's connection fix, because doing so properly wasn't possible with the current tools; writing that limitation down plainly was treated as more honest than adding a test that wouldn't really prove anything.
5. **New capability was added without disturbing what already worked.** Today's filtering options were built to compose with the filters already in place, and the automatically-computed month label was designed to upgrade older data safely rather than requiring anything to be redone by hand.
