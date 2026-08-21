# Learning Summary Convention

**Location & naming:** `docs/learnings/learning_summary_DD-Mon-YYYY.md` (e.g. `learning_summary_20-Aug-2026.md`). One file per day worked on the project.

**Cadence:** Created at the end of each day that has DEVLOG.md session entries — not proactively, only for days with actual recorded work.

**Source of truth:** `docs/DEVLOG.md` is the only source. Every claim in the summary must trace back to something actually recorded there for that day — no aspirational statements, no claims about "what's next" or "what this means for the project" unless that was explicitly discussed and logged. (We caught and fixed a violation of this: a "Key Learning" claimed a UI/browser-view direction had been "recognized" that day — it hadn't; nothing in DEVLOG supported it. Ground everything, or leave it out.)

**Audience & tone:** Non-technical, plain English. No code paths, no function/module names, no session numbers, no jargon. Brief and professional — someone with zero context on the codebase should be able to read it and understand what happened and why it mattered.

**Structure** (exact heading shape, must match existing files):

```markdown
# Learning Summary — DD Mon YYYY

## What We Achieved
- Bullet list, plain-English outcomes (what changed / became possible)

## How We Achieved It
- Bullet list, the approach/discipline used — not implementation detail, but *how we worked* (e.g. "verified assumptions before relying on them," "built in small steps," "deferred features until there was a real need")

## Key Learnings
1. **Bold short takeaway.** 1-3 plain-English sentences explaining it, grounded in something that actually happened that day.
2. ...
```

**Length:** Brief — each bullet is one sentence or two; Key Learnings are usually 3-5 numbered points.
