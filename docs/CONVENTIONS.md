# Project Conventions

Process rules that govern how this project is worked on and documented.
For code-level invariants (rules about how shared code must behave), see
the "Invariants" section at the top of docs/DEVLOG.md instead — those
live near the code log by design.

## DEVLOG Entry Structure

Every session entry in docs/DEVLOG.md follows the same five-section shape:
Goal, What happened, Outcome, In plain English, and Next steps.

- **Goal** — one or two sentences on what the session set out to do.
- **What happened** — the technical detail: commands run, code written,
  decisions made. This is where the *why* behind each decision belongs,
  not just the *what*. A decision recorded without its reasoning is much
  less useful to a future reader — including a future session — trying to
  judge whether that reasoning still holds.
- **Outcome** — what works now that didn't before, and how it was
  verified.
- **In plain English** — two or three short paragraphs, no jargon, no
  file paths, no function names, no session numbers. What was built, why
  it mattered, what it unlocks. Every sentence here must trace back to
  something already stated in "What happened" or "Outcome" — this section
  translates, it never introduces a new claim. It's written so it can be
  lifted almost verbatim into a learning summary. If a decision's
  reasoning isn't captured in "What happened," there's nothing honest to
  translate into plain English here — that's a sign the technical section
  is incomplete, not a reason for this section to editorialize.
- **Next steps** — what's planned next.

**"In plain English" is required from Session 24 onward.** Sessions 1
through 23 predate this convention and are not retrofitted.

## Learning Summary Convention

**Location & naming:** `docs/learnings/learning_summary_DD-Mon-YYYY.md`
(e.g. `learning_summary_20-Aug-2026.md`). One file per day worked on the
project.

**Cadence:** Created at the end of each day that has DEVLOG.md session
entries — not proactively, only for days with actual recorded work.

**Source of truth:** `docs/DEVLOG.md` is the only source. Every claim in
the summary must trace back to something actually recorded there for that
day — no aspirational statements, no claims about "what's next" or "what
this means for the project" unless that was explicitly discussed and
logged. Ground everything, or leave it out.

**Audience & tone:** Non-technical, plain English. No code paths, no
function/module names, no session numbers, no jargon. Brief and
professional — someone with zero context on the codebase should be able
to read it and understand what happened and why it mattered.

**Structure** (exact heading shape, must match existing files):

```markdown
# Learning Summary — DD Mon YYYY

## What We Achieved
- Bullet list, plain-English outcomes (what changed / became possible)

## How We Achieved It
- Bullet list, the approach/discipline used — not implementation detail,
  but *how we worked* (e.g. "verified assumptions before relying on
  them," "built in small steps," "deferred features until there was a
  real need")

## Key Learnings
1. **Bold short takeaway.** 1-3 plain-English sentences explaining it,
   grounded in something that actually happened that day.
2. ...
```

**Length:** Brief — each bullet is one sentence or two; Key Learnings are
usually 3-5 numbered points.

## Data Handling in Documentation

**Rule:** when working with real financial data — imported bank
statements, actual transactions in the database — only counts,
reconciliation numbers, and statement period ranges may appear in any
documentation surface. This includes DEVLOG entries, learning summaries,
Claude Code prompts, README examples, screenshots, and chat transcripts
shared for review. Never merchant names, never amounts, never individual
transaction dates, never reference numbers, never reward point values.

**Why:** this project's DEVLOG and learning history are checked into git
and may be shared publicly, as a portfolio of the Claude Code learning
journey. Real credit card statement content should never end up in a
public git history — not the statement file itself (already git-ignored),
and not fragments of it quoted into documentation either.

This rule exists because of two lived incidents, not as a hypothetical
precaution:

1. **Session 5's password leak.** A real password was pasted verbatim
   into a Claude Code prompt, and — because DEVLOG entries quote the
   prompt given verbatim — it got logged into DEVLOG and committed.
   Fixing it required `git commit --amend` to remove the password from
   git history, not just editing the file forward.
2. **Session 23's manual endpoint verification.** A curl response body
   containing five real transactions was pasted into a review chat.
   Caught and named at the time, and nothing lasting was committed — but
   it's the same category of mistake as (1): real data crossing into a
   documentation or review surface it should never reach.

The rule applies to every surface, not just Claude Code prompts — a
screenshot or a pasted terminal output is exactly as much of a leak as a
logged prompt.

**Exploration output files.** Exploration output files
(`data/exploration_output*.txt`) contain raw extracted text from real bank
statements — account details, merchant names, amounts, dates, everything.
They are git-ignored under the `data/` rule and must never be committed,
pushed, or shared. They exist only for local review during parser
development. If the project is ever published to GitHub or shared
externally, verify these files are not included — the `.gitignore` rule
protects against normal `git add`/`push`, but manual uploads, zip
archives, or alternative publishing methods could bypass it.

## CLI Invocation

**Rule:** every script under `scripts/` must be run as
`python3 -m scripts.<name>` from the project root, with the virtual
environment active — never invoked directly as `python3
scripts/<name>.py`.

**Why:** running a script directly puts *that script's own directory* on
`sys.path`, not the project root. Every script's top-level `from
storage...` imports depend on the project root being on `sys.path`, so a
direct invocation fails with `ModuleNotFoundError`. Running the script as
a module (`-m`) from the project root puts the root on `sys.path`
correctly.

This rule is already documented in two other places — each script carries
a module docstring stating it, and the README's "Running the CLIs"
section covers it with an example per script — but this section is the
canonical statement of the rule; the other two exist for convenience at
the point of use, not as a separate source of truth.

## Session Methodology

The discipline this project is built under, session after session:

- **Scope is locked before code.** Every session's scope is agreed upon in
  conversation, decision by decision, before any Claude Code prompt is
  written. A prompt is a record of an already-made decision, not a place
  to make one.
- **One prompt, one logical unit.** Large features are broken into
  sequential prompts across multiple sessions rather than bundled into one
  large prompt. If a prompt starts trying to do several unrelated things,
  it should be split.
- **Claude Code builds, Chandra verifies.** Verification against a running
  server or real data happens in a separate terminal, run by Chandra —
  never by Claude Code. Claude Code does not start `uvicorn`, does not run
  `curl` against a live endpoint, and does not touch `data/tracker.db`
  unless a prompt explicitly says otherwise for a specific, scoped reason.
- **Documentation is never a separate step.** Every prompt that makes real
  build progress updates `docs/DEVLOG.md` in the same session. There is no
  such thing as "code now, document later."
- **One commit per session.** All of a session's changes — code, tests,
  docs, dependency changes — land in a single commit, so the git history
  reads as one logical unit per session.
- **Anti-speculation rule.** Features are not generalized or built ahead
  of need. A second bank parser doesn't get built until a second real
  bank statement exists to test it against; an abstraction doesn't get
  introduced until a second concrete case justifies its shape. Deferred
  work is named explicitly in a session's "Next steps," not built
  speculatively "while we're in there."
- **Real gaps get filled, not just noted — but only real ones.** The
  standing heuristic: if the code makes a promise no test currently
  verifies, that's a real gap worth closing in the same session. A
  feature nobody asked for yet is not a gap; it's speculation, and it
  waits.
- **Every session's final report states its session number.** The
  report Claude Code gives back at the end of a prompt — the summary of
  what was built, wherever it is delivered: terminal, chat interface, or
  any other surface — must explicitly name the session number it just
  completed, matching the number used in that session's own
  `docs/DEVLOG.md` entry; e.g. "Session 59 committed as `<hash>`."
  **Why:** Chandra relays these reports into a separate Claude
  conversation used for scoping and review, and that conversation has no
  independent way to confirm which session number a given report
  corresponds to. Explicit numbering keeps both conversations in sync
  without relying on manual tracking. (Added in Session 59.)

## Verification Tooling

Ad hoc scripts used to manually verify behavior (curl one-liners, quick
Python snippets) are themselves worth getting right, not just the code
they're checking — a wrong verification script produces a false result
that looks exactly like a passing one.

**Lesson (Session 23):** a count-checking one-liner assumed every JSON
response was a list and called `len()` on it without checking. FastAPI
error responses are JSON objects (`{"detail": "..."}`), and `len()` on a
dict returns its key count — so an error response was silently reported
as "1 result" instead of surfacing as an error. The endpoint was correct;
the verification script wasn't. Any ad hoc verification snippet that
assumes a response shape should type-check first (e.g. `isinstance(d,
list)`) before treating the response as data, so a malformed or
error response fails loudly instead of quietly passing as a plausible-
looking number.
