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

---

## Session 8 — 2026-08-13

### Goal
Turn the structural findings from Session 7 into an actual parser: a shared parser
interface, an HDFC implementation, and a reconciliation check against the
statement's own summary totals — without printing any real transaction data.

### What happened

**Prompt given to Claude Code:**
> "Create parsers/base.py defining a simple interface: a function signature
> parse(pdf_path: str, password: str) -> list[dict]... Create parsers/hdfc.py
> implementing this for HDFC statements... Classify a row as 'credit' if the
> description contains payment/refund keywords (PAYMENT, REFUND, REVERSAL,
> CASHBACK, CREDIT) OR if its amount matches the 'PAYMENTS/CREDITS RECEIVED' total
> from the page-1 summary box. Otherwise classify as 'debit'. Write a helper that
> also extracts the page-1 summary box's key totals... sum all debit amounts and
> compare against the summary box's spend total; sum all credit amounts and compare
> against the credits-received total. Print whether both reconcile (match) or not.
> Test this against data/statements/hdfc_sample.pdf... Do not print individual
> transaction rows... only print the reconciliation totals (do they match, yes/no)
> and the count of transactions parsed, debits vs credits."

**`parsers/base.py`:**
Defines the shared contract as a `Transaction` `TypedDict` (`date`, `description`,
`amount`, `type`, `reward_points`) plus a `ParseFn` type alias documenting that every
parser module exposes `parse(pdf_path: str, password: str) -> list[Transaction]`. Kept
intentionally minimal — no abstract base class, since a type alias is enough to
document and check the contract for a single implementation.

**`parsers/hdfc.py`:**
- `_TXN_LINE_RE` — a single regex matching one transaction line as it comes out of
  `extract_text()`: date, `|`, time, description, an optional `+ <points>` (reward
  points earned), an optional lone `+` (present on the one non-purchase/payment line,
  with no digits after it), then the currency-prefixed amount, then the trailing icon
  glyph. Built and reasoned through against the exact line shapes recorded in
  `data/exploration_output.txt` during Session 7 (not reproduced here).
- `extract_summary()` — parses the page-1 summary box out of `extract_text()`
  output: finds the line ending in `=` (which holds, in order, previous statement
  dues / payments-credits received / purchases-debit / finance charges) and the line
  starting with `_` (total amount due). This is explicitly tailored to this
  statement's specific text-extraction quirks (documented in the code) — a fragile
  approach, not a general-purpose summary-box parser.
- `_classify()` — implements the requested rule exactly: credit if the description
  contains a payment/refund/reversal/cashback/credit keyword, OR if the amount matches
  the summary box's credits-received total (within a cent, to allow for float
  rounding); debit otherwise.
- `parse()` — opens the PDF once per page, regex-matches every line, and builds a
  `Transaction` dict per match, using `extract_summary()`'s credits-received figure to
  drive `_classify()`.

**`run_hdfc_parser.py`:**
A small script (same pattern as `read_statement.py` / `explore_structure.py`) that
loads the password from `.env`, calls `parse()` and `extract_summary()`, sums debit
and credit amounts, and compares each sum against the corresponding summary-box
total (tolerance: 1 cent, to absorb float rounding). Deliberately prints **only**
the transaction count (split debit/credit) and yes/no reconciliation results — never
the sums themselves, individual rows, merchant names, or dates, since those are real
personal financial data.

```bash
python run_hdfc_parser.py
```
Output:
```
Transactions parsed: 26 (25 debit, 1 credit)
Debit total reconciles with statement summary: yes
Credit total reconciles with statement summary: yes
```

### Outcome
Parser interface (`parsers/base.py`) and HDFC implementation (`parsers/hdfc.py`)
written and working. Against the sample statement: 26 transactions were parsed (25
classified as debit, 1 as credit — matching the single payment/credit line identified
structurally in Session 7), and both the debit-sum and credit-sum reconcile exactly
with the statement's own summary-box totals. This is a strong signal the regex line
format and the classification rule are both correct for this statement. No real
transaction data (amounts, merchant names, dates) was printed to the terminal or
written into this log — only counts and match results, none of which are sensitive.

### Next steps
Try the parser against a second/different statement (or month) to see whether the
regex and summary-box parsing generalize, or whether they're overfit to this one
sample's exact layout. Consider what to do with transactions that don't match
`_TXN_LINE_RE` at all (currently silently skipped).

---

## Session 9 — 2026-08-13

### Goal
Run the parser against a second sample statement (`hdfc_sample_2.pdf`) to test
whether Session 8's regex and classifier generalize, and fix whatever breaks.

### What happened

**Prompt given to Claude Code:**
> "Run the existing parsers/hdfc.py against a second sample statement at
> data/statements/hdfc_sample_2.pdf, using the same password from .env... Reuse
> run_hdfc_parser.py's logic but point it at this new file, either by
> parameterizing the script to accept a file path argument or creating a second
> small script, whichever is cleaner. Report only: transaction count (debit vs
> credit), and whether both totals reconcile... If reconciliation fails or the
> transaction count looks wrong, investigate why... and report what needs to
> change in the regex/classifier."

**`run_hdfc_parser.py` change:**
Parameterized rather than duplicated: added an optional positional `pdf_path`
argument (via `argparse`, defaulting to the original sample) so the same script
works against any statement file.

**Initial result against `hdfc_sample_2.pdf`:** both debit and credit totals failed
to reconcile.

**Investigation (all done via local diagnostics — descriptions/amounts inspected
locally, never printed to chat):**
1. Checked for transaction-shaped lines (starting with a date) that the regex
   failed to match at all — none found. Every date-prefixed line matched.
2. Checked for any currency-bearing line missed entirely (outside known
   summary/EMI-total rows) — none found on any of the 3 pages.
3. Verified the summary box's column order/positions by testing the statement's
   own arithmetic identity (`previous_dues − credits_received + purchases_debit +
   finance_charges = total_amount_due`) against all orderings of the 4 extracted
   summary amounts — confirmed `payments_credits_received` was being read from the
   correct position.
4. Computed the debit-side and credit-side reconciliation gaps and found they were
   exactly equal in magnitude and opposite in sign — proof the total parsed amount
   was correct, just split wrong between the two buckets (conservation check:
   `sum(all parsed transactions) == purchases_debit + payments_credits_received`,
   confirmed true).
5. Searched combinations of debit-classified transactions for one whose amount (or
   small sum of amounts) equalled the shortfall — found a single debit-classified
   transaction whose amount exactly matched.
6. Inspected that transaction's parsed fields (lengths/shapes only): its
   `reward_points` was `None`, and its description ended in a stray digit token —
   a sign the parser had absorbed something it should have treated as structured
   data. Checking the two raw tokens immediately preceding the amount on that line
   showed the reward-points-shaped digit and the `+` in **reversed order**
   (`<digits> +` instead of the usual `+ <digits>`) compared to every other line.

**Root cause:** the regex's second `+` alternative (matching a bare `+` directly
before the amount, with no digits — previously only used to *tolerate*, not
*classify*) is exactly the shape of a non-purchase (payment/refund) line: it's the
same shape the one correctly-classified credit transaction has in Session 8's
sample. This second statement has **two** such lines, but only one contains a
recognizable keyword (`PAYMENT`); the other has no keyword and its amount doesn't
individually equal the full credits-received total (since that total is the *sum*
of both credit lines) — so it fell through both existing classification rules and
landed in "debit". The amount-equality fallback is inherently fragile whenever a
statement has more than one credit-type transaction, since no single transaction's
amount will equal an aggregate total in that case.

**Fix applied to `parsers/hdfc.py`:**
- `_TXN_LINE_RE`'s bare-`+` alternative is now a named group (`credit_marker`)
  instead of an unnamed, discarded one — its presence is now visible to the caller
  instead of just being silently consumed.
- `_classify()` gained a third rule: treat a bare `credit_marker` (with no reward
  points captured) as a credit signal, checked after keywords and before the
  amount-equality fallback.
- `parse()` now passes `has_credit_marker` through to `_classify()`.

**Re-verification after the fix:**
```bash
python run_hdfc_parser.py
python run_hdfc_parser.py data/statements/hdfc_sample_2.pdf
```
```
Transactions parsed: 26 (25 debit, 1 credit)
Debit total reconciles with statement summary: yes
Credit total reconciles with statement summary: yes

Transactions parsed: 12 (10 debit, 2 credit)
Debit total reconciles with statement summary: yes
Credit total reconciles with statement summary: yes
```
The first statement's result is unchanged (its one credit line already had a
keyword match, so the new rule doesn't affect it) — confirming the fix is additive,
not a regression.

### Outcome
`hdfc_sample_2.pdf` now parses and reconciles correctly (10 debit, 2 credit), and
`hdfc_sample.pdf` continues to reconcile as before. The classifier's amount-equality
fallback is confirmed fragile for statements with multiple credit-type transactions;
the structural bare-`+` marker turned out to be the more reliable signal, matching
what was worked out analytically (before any code was written) back when discussing
how to tell debits from credits in this statement format.

### Correction: the "reversed token order" was actually a minus sign
After reporting the above as a known limitation, it was clarified (by the account
holder, who recognized the transaction) that this line isn't a token-order quirk at
all: it's a **merchant refund** of an earlier purchase. The merchant name repeats
(refunds show up under the original merchant, not as a distinctly labeled line,
which is why no keyword ever catches it), and because the original purchase had
earned reward points, the refund **claws those points back** — shown in the raw
text as a minus sign before the points count: `MERCHANT − 65 + C <amount> l`. What
looked like reversed token order (`['65', '+']`) was actually the last two tokens
of a longer `- 65 +` sequence — the leading `-` had been getting silently absorbed
into `description` because `_TXN_LINE_RE`'s points group only ever recognized a
leading `+`.

**Fix applied to `parsers/hdfc.py`:**
- `_TXN_LINE_RE`'s points group is now sign-aware: `(?P<points_sign>[+-])\s*(?P<points>\d+)` instead of a hardcoded `\+`, so it captures `- 65` the same way it captures `+ 80`.
- `parse()` now applies that sign, so `reward_points` comes out negative
  (e.g. a clawback) instead of `None` with the digits stuck in `description`.

**Re-verification:**
```bash
python run_hdfc_parser.py
python run_hdfc_parser.py data/statements/hdfc_sample_2.pdf
```
Both statements still reconcile exactly as before (26 txns / 25 debit / 1 credit,
and 12 txns / 10 debit / 2 credit respectively) — this fix only affects the
`reward_points` and `description` fields, not classification or amounts. Confirmed
the refund line's `reward_points` is now negative and its `description` no longer
ends in a stray digit.

### Outcome
`hdfc_sample_2.pdf` parses and reconciles correctly (10 debit, 2 credit), with
correctly signed reward points on the refund/clawback line, and `hdfc_sample.pdf`
continues to reconcile as before. Two real gaps were found and fixed in this
session: (1) the classifier's amount-equality fallback breaks whenever a statement
has more than one credit-type transaction — fixed by using the structural bare-`+`
marker as a classification signal; (2) the points-parsing regex assumed points are
always non-negative — fixed by making the sign explicit in the regex instead of
hardcoded.

### Next steps
Consider testing against a statement with zero credit transactions and one with
more than two, to further stress-test the classifier and the points-sign handling.

---

## Session 10 — 2026-08-13

### Goal
Run the parser against a third sample statement (`hdfc_sample_3.pdf`) as a further
generalization check after Session 9's fixes.

### What happened

**Prompt given to Claude Code:**
> "Run the existing parsers/hdfc.py against a third sample statement at
> data/statements/hdfc_sample_3.pdf, using run_hdfc_parser.py's existing file-path
> argument... If reconciliation fails or the transaction count looks wrong,
> investigate using the same systematic approach as before... Report what pattern
> broke and what was fixed, not the actual values."

```bash
python run_hdfc_parser.py data/statements/hdfc_sample_3.pdf
```
Output:
```
Transactions parsed: 26 (25 debit, 1 credit)
Debit total reconciles with statement summary: yes
Credit total reconciles with statement summary: yes
```

Reconciled cleanly on the first attempt — no unmatched lines, no missed currency
rows, no classification gap, so none of the Session 9-style diagnostics were needed.

**Re-verification across all three sample statements**, to confirm nothing
regressed:
```bash
python run_hdfc_parser.py
python run_hdfc_parser.py data/statements/hdfc_sample_2.pdf
python run_hdfc_parser.py data/statements/hdfc_sample_3.pdf
```
```
Transactions parsed: 26 (25 debit, 1 credit)      # sample 1
Debit total reconciles with statement summary: yes
Credit total reconciles with statement summary: yes

Transactions parsed: 12 (10 debit, 2 credit)      # sample 2
Debit total reconciles with statement summary: yes
Credit total reconciles with statement summary: yes

Transactions parsed: 26 (25 debit, 1 credit)      # sample 3
Debit total reconciles with statement summary: yes
Credit total reconciles with statement summary: yes
```

### Outcome
All three sample statements now parse and reconcile correctly with no code changes
needed in this session. This is a useful data point: Session 9's fixes (the
bare-`+` credit marker and signed reward points) weren't overfit to
`hdfc_sample_2.pdf` specifically — they held up against a third, independent
statement.

### Next steps
A fourth sample statement (`hdfc_sample_4.PDF`) is now also present in
`data/statements/` but has not yet been tested. Try it next — note its filename
has an uppercase `.PDF` extension, which is fine for `pdfplumber`/the file system
on macOS but worth being aware of if any future path-matching logic is added
(e.g. globbing for `*.pdf` would miss it on a case-sensitive filesystem).

---

## Session 11 — 2026-08-13

### Goal
Run the parser against a fourth sample statement (`hdfc_sample_4.PDF`) — flagged in
advance as likely using an older HDFC template — and make the parser handle
whichever layout it turns out to be, not just report failure.

### What happened

**Prompt given to Claude Code:**
> "Run it against hdfc_sample_4.PDF too. the 4th statement structure is probably
> different. this is an old statement. I think bank change the layout recently
> hence the structure differs. but we should be able to do the job irrespective
> of it."

**Initial result:**
```bash
python run_hdfc_parser.py "data/statements/hdfc_sample_4.PDF"
```
```
Transactions parsed: 0 (0 debit, 0 credit)
Debit total reconciles with statement summary: unknown (summary total not found)
Credit total reconciles with statement summary: unknown (summary total not found)
```
Zero transactions *and* failed summary extraction — a much bigger gap than Sessions
9/10 (which were single-transaction misclassifications). This pointed at a
structurally different template rather than a data edge case, matching the
prediction.

**Investigation:** dumped the statement's raw text to a local, git-ignored file
(`data/exploration_output_4.txt`, same pattern as `explore_structure.py`'s output)
and reviewed it locally. Confirmed a genuinely different layout, not a variant of
the current one:
- No currency-symbol prefix on amounts at all (current layout uses a "C" glyph
  before every amount; this layout has bare numbers).
- No `|` between date and time; time (when present — it's sometimes omitted
  entirely) includes seconds, not just hours:minutes.
- Reward points appear as a bare, unsigned integer token — no `+`/`-` prefix.
- Credits are marked with a literal `Cr` suffix glued directly onto the amount
  (no space) — an explicit, unambiguous marker, unlike the current layout's bare
  `+` heuristic.
- The summary box has no `=`/`_` line anchors — it's a labeled "Account Summary"
  section followed by a line of five plain numbers.

**Design decision:** rather than trying to make one regex/summary-parser handle
both templates, added a second implementation and an auto-detecting dispatcher:
- **`parsers/hdfc_legacy.py`** (new) — implements the same `parse()`/
  `extract_summary()` contract from `parsers/base.py` for this older layout.
  - `_TXN_LINE_RE` matches date, optional `HH:MM:SS` time, description, optional
    bare reward-points integer, amount, optional glued-on `Cr` suffix.
  - A guard rejects any regex match whose description contains no letters at
    all — needed because the statement's own "Payment Due Date / Total Dues /
    Minimum Amount Due" summary row (`08/03/2025 58,611.00 9,560.00`) is
    date-prefixed and number-heavy enough that, without this check, it could be
    misparsed as a real (nonsensical) transaction line.
  - `extract_summary()` locates the 5-number "Account Summary" line by looking,
    line by line, for the first line *after* the "Account Summary" header whose
    tokens are all amount-shaped and number exactly five — avoiding both the
    differently-sized "Past Dues" row (6 numbers) and a same-shaped 5-number GST
    summary row that exists elsewhere in the document (excluded by only scanning
    page 1, where the GST summary doesn't appear).
  - Classification is just "credit if the `Cr` suffix is present, debit
    otherwise" — deliberately *not* keyword-based here, since a legitimate
    purchase line in this statement contains the word "PAYMENTS" as part of a
    merchant-EMI description, which would have produced a false positive under
    the current layout's keyword rule.
- **`parsers/hdfc.py`** — renamed its existing implementation functions to
  `_parse_current_layout()` / `_extract_summary_current_layout()` (unchanged
  internally), added `_detect_layout()` (sniffs page 1 for `"PAYMENTS/CREDITS"`
  vs `"Account Summary"` as landmark strings), and made `parse()` /
  `extract_summary()` public dispatchers that pick the right implementation
  based on detected layout. `run_hdfc_parser.py` needed no changes — it still
  just calls `parse()`/`extract_summary()` from `parsers.hdfc`.

**Re-verification after the fix:**
```
sample 1: 26 txns (25 debit, 1 credit) — reconciles: yes / yes
sample 2: 12 txns (10 debit, 2 credit) — reconciles: yes / yes
sample 3: 26 txns (25 debit, 1 credit) — reconciles: yes / yes
sample 4: 22 txns (21 debit, 1 credit) — reconciles: yes / yes
```
Also spot-checked (locally, shapes/lengths only) that all 22 of sample 4's parsed
transactions have letter-containing descriptions, confirming the summary-row guard
correctly filtered out the one line it was designed to catch without rejecting any
real transaction.

### Outcome
All four sample statements — spanning two structurally different HDFC layouts —
now parse and reconcile correctly through the same public `parsers.hdfc.parse()` /
`extract_summary()` entry points, with format detection happening automatically.
No caller-facing changes were needed in `run_hdfc_parser.py`.

### Next steps
If a third layout ever shows up, the `_detect_layout()` landmark-string approach
should extend cleanly (add a new landmark check and a new `parsers/hdfc_<name>.py`
module). Consider whether `_detect_layout()`'s `ValueError` on an unrecognized
layout is the right failure mode, or whether callers should get a clearer
"unsupported statement format" message.

---

## Session 12 — 2026-08-13

### Goal
Run the parser against two newly added sample statements (`hdfc_sample_5.PDF`,
`hdfc_sample_6.pdf`) to further test both layout paths, and fix whatever breaks.

### What happened

**Prompt given to Claude Code:**
> "I added 2 more samples - hdfc_sample_5 and hdfc_sample_6 - run against both to
> check integrity of our script."

```bash
python run_hdfc_parser.py "data/statements/hdfc_sample_5.PDF"
python run_hdfc_parser.py "data/statements/hdfc_sample_6.pdf"
```
```
Transactions parsed: 33 (31 debit, 2 credit)   # sample 5
Debit total reconciles with statement summary: yes
Credit total reconciles with statement summary: yes

Transactions parsed: 29 (26 debit, 3 credit)   # sample 6
Debit total reconciles with statement summary: no
Credit total reconciles with statement summary: no
```
Sample 5 detected as `legacy` layout and reconciled cleanly on the first try — a
good sign that Session 11's legacy parser generalizes, not just fits
`hdfc_sample_4.PDF`. Sample 6 detected as `current` layout and failed to reconcile.

**Investigation (same systematic approach as Session 9, all done locally):**
1. Checked for unmatched date-prefixed or currency-bearing lines — none found;
   every real transaction line matched.
2. Verified debit-gap and credit-gap magnitudes were exactly equal and opposite
   (conservation check), confirming a classification issue, not a missing/garbled
   line.
3. Searched combinations of debit-classified transaction amounts (up to 5) for one
   summing to the credit shortfall — found nothing, unlike Session 9's single-line
   case.
4. Inspected the credit-classified side instead of the debit side this time: 3
   transactions were classified credit, all 3 matched the `PAYMENT` keyword. Two
   were the expected same-shaped statement-payment reference lines (desc length 66,
   matching the known pattern); the third had a much shorter description starting
   with `AMAZON`.
5. Tested the hypothesis directly: recomputing the credit shortfall with that
   `AMAZON`-prefixed transaction excluded from the credit bucket brought it to
   (near) zero — strong evidence it was a false-positive credit classification, not
   a missing one.
6. Confirmed why: its description contains `PAYMENT` only as a substring inside a
   longer glued-together token (word lengths, not content, checked locally) — the
   same city/merchant-name concatenation pattern this statement format uses
   elsewhere (e.g. `SELLERSERVICESBANGALORE`-style tokens seen in earlier
   sessions). Verified with `\bPAYMENT\b` that a real standalone-word match (like
   the correctly-classified payment lines) succeeds while the glued-token case
   does not.

**Root cause:** `_classify()`'s keyword check used plain substring matching
(`keyword in upper_desc`), so `"PAYMENT"` matched inside merchant/city tokens like
`"...PAYMENTSBANGALORE"` even though that's an ordinary purchase, not a credit —
the exact class of false positive already flagged as a *risk* for the legacy
parser back in Session 11, now confirmed to actually occur in the current-layout
parser too.

**Fix applied to `parsers/hdfc.py`:**
`_classify()` now checks each keyword with a word-boundary regex
(`re.search(rf"\b{keyword}\b", upper_desc)`) instead of plain substring
containment, so `PAYMENT` only matches as its own word.

**Re-verification across all six sample statements:**
```
sample 1: 26 txns (25 debit, 1 credit)  — reconciles: yes / yes  (unchanged)
sample 2: 12 txns (10 debit, 2 credit)  — reconciles: yes / yes  (unchanged)
sample 3: 26 txns (25 debit, 1 credit)  — reconciles: yes / yes  (unchanged)
sample 4: 22 txns (21 debit, 1 credit)  — reconciles: yes / yes  (unchanged)
sample 5: 33 txns (31 debit, 2 credit)  — reconciles: yes / yes  (unchanged)
sample 6: 29 txns (27 debit, 2 credit)  — reconciles: yes / yes  (fixed: was 26/3)
```

### Outcome
All six sample statements — across both HDFC layouts — now parse and reconcile
correctly. The fix was narrowly scoped (one line, in the current-layout
classifier's keyword check) and didn't change any other statement's result.

### Next steps
The legacy parser deliberately avoided keyword-based classification from the start
(Session 11), specifically because of this exact risk — this session is a
confirmation that decision was warranted. Worth periodically re-checking new
CREDIT_KEYWORDS additions (if any) against real merchant-name concatenation
patterns before assuming substring matching is safe anywhere in this codebase.

---

## Session 13 — 2026-08-13

### Goal
Add unit tests for `parsers/hdfc.py` and `parsers/hdfc_legacy.py`, covering the
regex parsing and classification logic that Sessions 9, 11, and 12 had only been
tested manually (via `run_hdfc_parser.py` against real sample PDFs).

### What happened

**Prompt given to Claude Code:**
> "Add unit tests for parsers/hdfc.py and hdfc_legacy.py"

**Design decision — refactor first:** both parser modules previously mixed PDF
opening (`pdfplumber.open(pdf_path, password=...)`) directly into the same
functions that did the actual text parsing. Unit-testing that as-is would have
meant either opening real password-protected statement PDFs from tests (coupling
the test suite to real personal financial data and a real password), or not
testing the actual parsing logic at all. Instead, refactored each module to
separate pure text-processing functions from thin PDF-opening wrappers:
- `parsers/hdfc.py`: extracted `_extract_summary_current_layout_from_text(text)`,
  `_parse_line_current_layout(line, credits_received_total)`, and
  `_detect_layout_from_text(text)` as pure functions operating on strings. The
  existing public `parse()` / `extract_summary()` (and `_detect_layout()`) became
  thin wrappers: open the PDF, get the text, delegate to the pure function. No
  behavior change — same regexes, same classification logic, just relocated.
- `parsers/hdfc_legacy.py`: same pattern — extracted `_extract_summary_from_text(text)`
  and `_parse_line(line)`.

**Regression check before writing any tests:** re-ran `run_hdfc_parser.py` against
all six real sample statements after the refactor, before adding a single test, to
make sure moving code around hadn't silently changed behavior:
```
sample 1: 26 txns (25 debit, 1 credit)  — reconciles: yes / yes
sample 2: 12 txns (10 debit, 2 credit)  — reconciles: yes / yes
sample 3: 26 txns (25 debit, 1 credit)  — reconciles: yes / yes
sample 4: 22 txns (21 debit, 1 credit)  — reconciles: yes / yes
sample 5: 33 txns (31 debit, 2 credit)  — reconciles: yes / yes
sample 6: 29 txns (27 debit, 2 credit)  — reconciles: yes / yes
```
All identical to pre-refactor results.

**`requirements.txt`:** added `pytest`, installed into `venv`.

**`tests/test_hdfc.py`** (16 tests) and **`tests/test_hdfc_legacy.py`** (10 tests) —
all built around **fabricated** example lines (fake merchant names like "FAKE
MERCHANT ONE", fake reference numbers, round-number amounts), never real
transaction data from any sample statement. Coverage includes:
- `_to_float` comma-stripping.
- `_detect_layout_from_text` for both known layouts and the unrecognized-layout
  error case.
- Per-line parsing for: plain debit, debit with positive reward points, credit via
  the bare-`+` marker, credit via negative (clawback) points, credit via a
  standalone keyword, and — as a regression test for Session 12's fix — a
  merchant/city token that contains "PAYMENT" only as a substring (must classify
  as debit, not credit).
- The amount-equality fallback classification path.
- Non-matching lines returning `None` instead of raising.
- `extract_summary`-equivalent parsing for both the current layout's `=`/`_`-anchored
  format and the legacy layout's "Account Summary"-anchored format, including a
  test that a same-shaped 5-number line *before* the "Account Summary" header
  (mirroring the real GST-summary-row collision risk identified in Session 11)
  is correctly ignored.
- The legacy parser's numeric-only-line guard (the regression test for the
  `08/03/2025 58,611.00 9,560.00`-style false-positive risk from Session 11).

One test initially failed — a copy-paste bug in the test itself (a legacy-style
`HH:MM:SS` timestamp used in a current-layout test line, which doesn't have a `|`
separator and uses `HH:MM`), not a bug in the parser. Fixed the test's fabricated
input and re-ran.

```bash
python -m pytest tests/
```
```
26 passed in 0.06s
```

### Outcome
26 unit tests added, all passing, running in well under a second with no PDF I/O,
no real password, and no real financial data anywhere in the test suite. The
refactor that made this possible is behavior-preserving, confirmed by an
identical-results regression check against all six real sample statements both
before writing tests and after.

### Next steps
Consider adding a thin integration-level test that runs `parsers.hdfc.parse()`
against one of the real sample PDFs (skipped in CI/by default if `.env`/the sample
file aren't present) as a belt-and-suspenders check that the wrappers themselves
(PDF opening, page iteration) still work, not just the pure logic.
