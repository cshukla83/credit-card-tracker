# Learning Summary — 08 Sep 2026

## What We Achieved
- The project's own status records, which had fallen behind by two banks and described work that finished some time ago, now match what the system actually does: four banks supported, every sample statement on file adding up against the bank's own printed totals.
- The next phase of work — labelling transactions and showing where money goes — was decided and written down in full, with three modules, a fixed build order, and the questions that genuinely have no answer yet listed as questions.
- Four scattered planning documents were consolidated into one requirements document listing everything planned in priority order, with a status and a source against each of the thirteen items.
- That requirements document is now also produced in a shareable form for people who have no reason to open the codebase, generated automatically from the written version rather than maintained separately.
- Two parallel lines of work were brought back together into one clean, unambiguous history, with no duplicated or conflicting entries.
- A generated file that was being stored in version control alongside the text it is built from is no longer stored twice.

## How We Achieved It
- Corrections were taken from the project's own build history rather than from memory, and the one number that mattered — how many real statements reconcile — was counted directly and then cross-checked a second way before being written down.
- The instructions for a session were checked against the actual documents before acting on them, which caught two details that did not match reality: a line described as living in one section actually lived in another, and a note that was to be left untouched did not exist at all.
- Where a statement was outdated in one respect but still true in another, it was reworded to say both things rather than deleted outright.
- Decisions were written down before any of the work was built, including the reasoning for each one, so that later readers can judge whether the reasoning still holds.
- A deliberate exception to one of the project's standing rules was scoped narrowly and in writing at the moment it was made, rather than left to be interpreted later.
- Questions that had no answer yet were recorded as open instead of being settled speculatively, on the basis that the work needing those answers comes last.
- When two histories collided, the resolution rule was agreed first and applied mechanically, then verified by rebuilding the result from both originals and confirming that nothing but the numbering had changed.
- What was deliberately left unfixed was named explicitly at the end of each session, rather than quietly omitted.

## Key Learnings
1. **A status document that is believed and wrong is worse than one nobody reads.** The pages describing this project's current state had quietly fallen two banks behind while the work moved on. Anyone trusting them would have been misled, which is a worse outcome than having no summary at all.
2. **When something is outdated in one way but still true in another, reword it rather than delete it.** One line said the system cannot yet work out which card a statement belongs to. That is still exactly how it behaves, so removing it would have made the documentation wrong in the opposite direction — but a decision to change it now exists. The line was rewritten to say both.
3. **Two hand-maintained copies of the same document will drift apart, and one of them usually cannot be checked.** The shareable version of the requirements is generated from the written one instead of being written twice, because a document in that format shows no visible history of changes — the two could disagree for a long time before anyone noticed.
4. **Check the instructions against the thing itself before acting on them.** Twice in one day a session's brief described a document slightly differently from how it actually was. Looking first cost minutes; acting on the description would have produced edits in the wrong place or a change with nothing to change.
5. **Fixing part of a problem can leave a document contradicting itself.** An earlier correction was deliberately scoped to certain sections, which left the opening description saying one bank was supported while a paragraph below it correctly said four. Partial fixes need their leftovers named, or the contradiction is what the next reader finds.
