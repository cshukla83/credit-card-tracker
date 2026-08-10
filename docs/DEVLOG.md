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
