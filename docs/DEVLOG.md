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
