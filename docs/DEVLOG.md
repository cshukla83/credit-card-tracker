# Development Log

This file is a detailed, chronological record of every working session on this project —
what was done, every command run, and what it means. Written so that anyone with no prior
context (including future-me) can follow along and understand each step.

Each entry follows this format:

```
## Session N — <date>

### Goal
What we set out to do this session.

### What happened
Step-by-step account, including:
- The exact prompt given to Claude Code (if used)
- Every command run, and what it does / why it was needed
- Any code written, with a short explanation of what it does
- Any errors hit, and how they were resolved

### Outcome
What works now that didn't before. What was verified (and how).

### Next steps
What's planned for the next session.
```

---

## Session 1 — <date>

### Goal
Set up the initial project scaffold: virtual environment, dependencies, and a minimal
working FastAPI app to confirm the setup works end to end.

### What happened

**Prompt given to Claude Code:**
> "Set up a basic Python project structure for a credit card statement tracker. Create a
> virtualenv, a requirements.txt with pdfplumber and fastapi, and a minimal FastAPI app
> that just returns 'hello world' at the root endpoint. Explain what each file does as
> you create it."

**Commands run:**

```bash
python3 -m venv venv
```
Creates `venv/` — an isolated Python environment local to this project. Packages
installed here don't affect system Python or other projects.

```bash
pip install -r requirements.txt
```
Installs the three dependencies listed in `requirements.txt`:
- `fastapi` — the web framework used to build the API
- `uvicorn[standard]` — the server that actually runs the FastAPI app
- `pdfplumber` — for extracting text/tables from PDF statements (used in a later session)

**Code written — `main.py`:**
```python
from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def read_root():
    return {"message": "hello world"}
```
- `app = FastAPI()` creates the application instance.
- `@app.get("/")` is a decorator registering `read_root()` as the handler for GET
  requests to `/`.
- The function's return value is automatically converted to JSON.

**Verification:**
```bash
source venv/bin/activate
uvicorn main:app --reload
```
Opened `http://127.0.0.1:8000/` in a browser — confirmed it returned
`{"message": "hello world"}`.

### Outcome
Working minimal FastAPI app confirmed end to end: environment set up, dependencies
installed, server runs, endpoint responds correctly.

### Next steps
Set up `.gitignore` and initialize git. Then begin building the PDF statement parser.

---

## Session 2 — 2026-08-10

### Goal
Initialize git, confirm `.gitignore` correctly excludes Python artifacts, make an
initial commit, and log the process here.

### What happened

**Prompt given to Claude Code:**
> "Initialize git in this project. Confirm the .gitignore (already present) correctly
> excludes venv/, __pycache__, .env, and other Python artifacts — add anything missing.
> Then stage and make an initial commit with a clear message. After that, append a new
> dated Session 2 entry to docs/DEVLOG.md following the existing format — documenting
> every git command run, what it does, and confirming the commit was made (include
> `git log` output)."

**Pre-existing issues found and fixed before initializing git:**
- A gitignore file existed but was named `gitignore` (no leading dot), so git would
  never have actually read it. Renamed it to `.gitignore`.
- `DEVLOG.md` was sitting at the project root, but the README's documented project
  structure (and this session's own instructions) place it at `docs/DEVLOG.md`. Moved
  it into a new `docs/` directory.

**`.gitignore` review:**
The existing file already covered `venv/`, `__pycache__/`, `*.pyc`, `.env`, `.DS_Store`,
`*.db`, and `data/`. Added a few more standard Python/project artifacts that were
missing:
```
.env.*
build/
dist/
*.egg-info/
.pytest_cache/
.mypy_cache/
.ipynb_checkpoints/
```

**Commands run:**

```bash
mv gitignore .gitignore
```
Renames the ignore file so git actually recognizes and applies it.

```bash
mkdir -p docs && mv DEVLOG.md docs/DEVLOG.md
```
Creates the `docs/` directory and moves the dev log into it, matching the structure
documented in `README.md`.

```bash
git init
```
Initializes a new, empty git repository in the project root (creates the `.git/`
directory). No commits exist yet after this step.

```bash
git status
```
Confirmed that `venv/`, `__pycache__/`, and `.DS_Store` did **not** appear in the
untracked-files list — proof the `.gitignore` is correctly excluding them. Only
`.gitignore`, `README.md`, `docs/`, `main.py`, and `requirements.txt` showed up as
untracked.

```bash
git add .gitignore README.md docs/DEVLOG.md main.py requirements.txt
```
Stages the real project files explicitly by name (rather than `git add .` or `-A`), so
nothing untracked/ignored/unexpected slips into the commit.

```bash
git commit -m "Initial commit: FastAPI scaffold for credit card statement tracker ..."
```
Creates the first commit on the `main` branch, recording the current project scaffold.
Git auto-configured the commit author from the local username/hostname (no global
`user.name`/`user.email` set yet) — flagged by git's own output, not changed since it
wasn't part of this task.

```bash
git log --stat
```
Confirms the commit exists and shows what it contains:

```
commit 823c5895171d433174e60664f9573a296343ea8d
Author: Chandra Prakash Shukla <chandra@Chandras-MacBook-Pro.local>
Date:   Mon Aug 10 19:47:16 2026 +0530

    Initial commit: FastAPI scaffold for credit card statement tracker

    Adds virtualenv-based project setup with a minimal FastAPI app
    (GET / -> hello world), requirements.txt (fastapi, uvicorn, pdfplumber),
    .gitignore for Python artifacts, README, and dev log.

 .gitignore       | 14 +++++++++
 README.md        | 55 ++++++++++++++++++++++++++++++++++
 docs/DEVLOG.md   | 89 ++++++++++++++++++++++++++++++++++++++++++++++++++++++++
 main.py          |  8 +++++
 requirements.txt |  3 ++
 5 files changed, 169 insertions(+)
```

```bash
git log --oneline
```
```
823c589 Initial commit: FastAPI scaffold for credit card statement tracker
```

### Outcome
Git repository initialized with a correct, working `.gitignore` (verified via
`git status` before committing — no ignored files were staged). Initial commit made on
`main` containing exactly the five intended files. Commit existence and contents
verified via `git log --stat` and `git log --oneline`.

### Next steps
Set `git config user.name` / `user.email` explicitly if the auto-detected identity
isn't correct. Begin building the PDF statement parser using `pdfplumber`.

---

## Session 3 — 2026-08-10

### Goal
Add support for opening a password-protected sample HDFC statement: install
`python-dotenv`, store the statement's password in a git-ignored `.env` file, and
write a script that loads it and extracts the first page's raw text with
`pdfplumber`.

### What happened

**Prompt given to Claude Code:**
> "Add python-dotenv to requirements.txt and install it. Create a .env file in the
> project root with a variable HDFC_SAMPLE_PASSWORD (I'll fill in the actual value
> myself after — leave it as a placeholder). Confirm .env is already covered by
> .gitignore. Then write a script that uses python-dotenv to load this password and
> opens data/statements/hdfc_sample.pdf with pdfplumber using it, printing the first
> page's raw text."

**Pre-existing issue found and fixed:**
The sample PDF actually existed at `data/statememts/HDFC-July2026-Statement.pdf` — the
directory name was misspelled ("statememts") and the filename didn't match what was
asked for. Confirmed with the user, then renamed both to match the intended path:
`data/statements/hdfc_sample.pdf`.

**Commands run:**

```bash
mv data/statememts data/statements
mv data/statements/HDFC-July2026-Statement.pdf data/statements/hdfc_sample.pdf
```
Fixes the directory spelling and renames the statement file so the path matches what
the script (and this session's instructions) expect.

**`requirements.txt` change:**
Added `python-dotenv` — a library that reads `KEY=value` pairs from a `.env` file and
loads them into `os.environ`, so secrets like statement passwords don't need to be
hardcoded or exported manually in the shell.

```bash
pip install -q python-dotenv
```
Installs the new dependency into the project's `venv`. Confirmed with `pip show
python-dotenv` (version 1.2.2).

**`.env` file created at the project root:**
```
HDFC_SAMPLE_PASSWORD=changeme
```
A new environment variable, `HDFC_SAMPLE_PASSWORD`, holding the password needed to
open the sample HDFC PDF statement with `pdfplumber` (password-protected statement
PDFs are common for Indian bank e-statements — typically some combination of
name/DOB/account digits set by the bank). Left as a `changeme` placeholder — the real
password is meant to be filled in locally by hand, not written by Claude Code, and is
**not** recorded anywhere in this log.

```bash
git check-ignore -v .env
```
Confirms `.env` is matched by the `.env` rule already present in `.gitignore` (added
in Session 2). Also confirmed with `git status --short`, which shows `.env` does not
appear at all — proof it's excluded, not just untracked.

**Code written — `read_statement.py`:**
```python
import os

import pdfplumber
from dotenv import load_dotenv

load_dotenv()

password = os.environ["HDFC_SAMPLE_PASSWORD"]
pdf_path = "data/statements/hdfc_sample.pdf"

with pdfplumber.open(pdf_path, password=password) as pdf:
    first_page = pdf.pages[0]
    print(first_page.extract_text())
```
- `load_dotenv()` reads the `.env` file in the current directory and populates
  `os.environ` with its keys, so no separate config-loading code is needed.
- `os.environ["HDFC_SAMPLE_PASSWORD"]` reads the password out of the environment
  rather than hardcoding it in source.
- `pdfplumber.open(pdf_path, password=password)` opens the (possibly encrypted)
  statement PDF using that password.
- `first_page.extract_text()` pulls the raw text layer off page 1 and prints it.

**Verification:**
```bash
python -m py_compile read_statement.py
```
Confirmed the script has no syntax errors. Did **not** run it end-to-end: the `.env`
password is still the `changeme` placeholder, so a real run would either fail (if the
PDF is encrypted) or print real personal financial data from the statement straight
into the terminal/session (if it isn't). Running it with the real password is left to
be done locally, by hand.

### Outcome
`python-dotenv` installed and added to `requirements.txt`. `.env` created with a
placeholder `HDFC_SAMPLE_PASSWORD` and confirmed to be git-ignored. Sample statement
PDF relocated to the expected path. `read_statement.py` written and syntax-verified,
ready to run once the real password is filled in locally.

### Next steps
Fill in the real `HDFC_SAMPLE_PASSWORD` value in `.env` (locally, not via Claude
Code) and run `read_statement.py` to confirm the password and text extraction both
work. Then move from printing raw text to actually parsing transactions out of it.

---

## Session 4 — 2026-08-10

### Goal
Fill in the real `HDFC_SAMPLE_PASSWORD` and verify `read_statement.py` end to end.

### What happened

**Prompt given to Claude Code:**
> "Update .env with the real HDFC statement password (provided separately, not
> included in this log)." — followed by "yes, run it" once asked whether to execute
> the script.

Replaced the `changeme` placeholder in `.env` with the real password. Re-confirmed via
`git status --short` that `.env` still did not appear (i.e. remains git-ignored) after
the edit.

```bash
python read_statement.py
```
Ran the script with the real password against `data/statements/hdfc_sample.pdf`.

### Outcome
Success — the password correctly decrypted the PDF and `pdfplumber` extracted page 1's
text. This verifies the full chain: `.env` → `python-dotenv` → `pdfplumber` password
handling → text extraction. The actual extracted statement text (account details,
transactions, balances) is **not** reproduced here, since it's real personal financial
data — only the fact that the run succeeded is logged.

### Next steps
Move from printing raw text to actually parsing structured transactions (date,
description, amount) out of the statement text.

---

## Session 5 — 2026-08-10

### Goal
Fix and document a secret-handling mistake: the real HDFC statement password was
logged verbatim in the Session 4 entry's "Prompt given to Claude Code" quote.

### What happened

**Prompt given to Claude Code:**
> "Append a new dated entry to docs/DEVLOG.md (Session 5) documenting that the real
> HDFC statement password was accidentally logged verbatim in Session 4's DEVLOG
> entry (now fixed via git commit --amend, confirmed removed from all git history via
> git log --all -p). Do not include the actual password value anywhere in this entry.
> Note the lesson: never include actual secret values in prompts when the instruction
> is to log prompts verbatim — set secrets directly in .env by hand instead."

**What went wrong:**
In Session 4, the actual password value was included directly in the prompt text
asking Claude Code to write it into `.env`. Because the DEVLOG convention is to quote
the prompt given to Claude Code verbatim, that same prompt — including the plaintext
password — was written into Session 4's DEVLOG entry and committed to git.

**Fix applied:**
- The Session 4 "Prompt given to Claude Code" quote was rewritten to describe the
  action without reproducing the secret value.
- The commit containing the leaked value was rewritten via `git commit --amend`.
- Verified removal with:
  ```bash
  git log --all -p | grep -i "<password>"
  ```
  Confirmed no match across all commits/refs, and confirmed no match in the current
  working tree.

### Outcome
The real password no longer appears anywhere in `docs/DEVLOG.md`, the current working
tree, or any commit reachable via `git log --all -p`. `.env` (git-ignored, never
committed) remains the only place the real value lives.

### Lesson learned
Never put an actual secret value inside a prompt when the instruction also asks for
that prompt to be logged verbatim — the secret will get copied straight into the log
(and, if committed, into git history) along with it. Instead, set secret values
directly in `.env` by hand (outside of any prompt text), and phrase prompts to Claude
Code in terms of *what* to do ("update .env with the real password") rather than
including the value itself.

### Next steps
Move from printing raw text to actually parsing structured transactions (date,
description, amount) out of the statement text.

---

## Session 6 — 2026-08-13

### Goal
Document that the global git identity was set locally (outside Claude Code), fixing
the auto-detected commit author flagged back in Session 2.

### What happened

**Prompt given to Claude Code:**
> "Append a dated entry to docs/DEVLOG.md documenting that git config --global
> user.name and user.email were set locally (outside any Claude Code session) after
> Session 2, to replace the auto-detected commit author. Confirm by running git
> config --global user.name and git config --global user.email and including that
> output (values only, this isn't sensitive)."

Between Session 2 and this session, `git config --global user.name` and `git config
--global user.email` were run by hand, outside of any Claude Code session, replacing
the locally-derived identity (`chandra@Chandras-MacBook-Pro.local`) that git had
auto-configured when the first commits were made. This is also what made it possible,
back in the follow-up to Session 2, to rewrite the existing commits' authorship via
`git rebase --root --exec "git commit --amend --reset-author --no-edit"`.

**Commands run:**

```bash
git config --global user.name
git config --global user.email
```
Reads back the currently configured global git identity to confirm what's in effect.

Output:
```
Chandra Prakash Shukla
64454270+cshukla83@users.noreply.github.com
```

### Outcome
Confirmed the global git identity is set to `Chandra Prakash Shukla
<64454270+cshukla83@users.noreply.github.com>`. All commits made in this repo from
here on will use this identity automatically, with no per-commit configuration
needed.

### Next steps
Move from printing raw text to actually parsing structured transactions (date,
description, amount) out of the statement text.

---

## Session 7 — 2026-08-13

### Goal
Explore the sample statement's structure more fully — all pages, plus pdfplumber's
table-extraction methods — to inform how transaction parsing should work later,
without pasting real financial data into chat.

### What happened

**Prompt given to Claude Code:**
> "Using read_statement.py as a base, write a small exploration script
> (explore_structure.py) that: 1. Opens data/statements/hdfc_sample.pdf with the
> password from .env 2. Prints the raw text of all pages (not just page 1) 3. Also
> tries pdfplumber's extract_table() / extract_tables() on each page and prints what
> it finds, if anything 4. Saves both outputs to a local, gitignored file
> (data/exploration_output.txt) rather than just printing to terminal, so we can
> review it without pasting real financial data into chat. Add
> data/exploration_output.txt to .gitignore. Append a Session entry to
> docs/DEVLOG.md documenting this exploration step and what was found."

**`.gitignore` change:**
Added an explicit `data/exploration_output.txt` line. Note: the existing `data/` rule
(added in Session 2) already covers this file, so the new line is redundant but kept
for clarity/self-documentation, per the request. Confirmed with `git check-ignore -v`
that the file is (and was already) ignored.

**Code written — `explore_structure.py`:**
Based on `read_statement.py`, but instead of only reading page 1 and printing to the
terminal, it:
- Loops over every page in the PDF (`pdf.pages`), not just the first.
- For each page, calls `.extract_text()`, `.extract_table()`, and `.extract_tables()`
  and records all three outputs.
- Writes everything to `data/exploration_output.txt` (creating `data/` if needed)
  instead of printing to stdout, so real statement contents never need to pass
  through the terminal/chat to be reviewed — only the output file path is printed.

```bash
python explore_structure.py
```
Ran the script; it wrote `data/exploration_output.txt` successfully. The file itself
was reviewed locally (via the file system, not pasted into this session).

**Structural findings (described generically — no real transaction data below):**
- The statement is 3 pages.
  - Page 1: account summary (dues, credit limit, rewards balance, card controls),
    followed by the start of a "Domestic Transactions" section with a handful of
    transaction rows at the bottom.
  - Page 2: the rest of the transaction list, followed by a transactions total and a
    rewards-points-program summary section.
  - Page 3: pure informational/legal text (terms, GST notes, useful links) — no
    transactions, no tables.
- Each transaction appears as **one raw-text line**, following a consistent shape:
  `DATE| TIME  DESCRIPTION  [+ POINTS]  AMOUNT  ICON`, all separated by whitespace
  rather than any visible column/ruling structure.
- `extract_table()` / `extract_tables()`:
  - On page 1, only picked up fragments of the summary boxes (e.g. the rewards-points
    box, the credit-limit box) as small tables — it did **not** capture the
    transaction rows as a structured table.
  - On page 2, it detected the transaction section as a table, but each transaction
    line came back as a single one-column row (the whole line as one cell) rather
    than being split into separate date / description / amount columns.
  - On page 3, no tables were found at all, consistent with it being plain paragraph
    text.
- Takeaway: `pdfplumber`'s automatic table detection doesn't cleanly separate
  transaction fields on this statement layout. Parsing transactions later will likely
  need a regex/positional approach over `extract_text()` output (matching on the
  date-time prefix and the amount suffix) rather than relying on
  `extract_table()`/`extract_tables()`.

### Outcome
`explore_structure.py` created and run successfully; full multi-page raw text and
table-extraction output saved to the git-ignored `data/exploration_output.txt` for
local review. Confirmed the general per-page structure and transaction line format,
and confirmed that table extraction is not reliable for this statement's transaction
section. No real statement content was pasted into chat or written into this log.

### Next steps
Write a regex-based parser over `extract_text()` output to turn each transaction line
into structured fields (date, time, description, amount, reward points), using the
line format identified in this session.
