# Learning Summary — 29 Jul 2026

## What We Achieved
- Stood up the initial project scaffold for the credit card statement tracker: an isolated Python environment, a dependency list, and a minimal working web app.
- Confirmed the whole setup works end to end, from a clean environment through a running server responding to a real request.

## How We Achieved It
- Created a dedicated virtual environment (`venv`) so project dependencies stay isolated from the system Python and other projects.
- Declared the project's core dependencies up front — `fastapi` (web framework), `uvicorn` (the server that runs it), and `pdfplumber` (for reading PDF statements later) — in a `requirements.txt`, then installed them.
- Wrote the smallest possible FastAPI app (a single endpoint returning a fixed response) as a deliberate "hello world" checkpoint, rather than building further before confirming the basics work.
- Verified the app by actually running the server and hitting the endpoint in a browser, instead of just trusting that the code looked correct.

## Key Learnings
1. **Start with the smallest working version.** A one-endpoint "hello world" app is a fast, low-risk way to confirm the environment, dependencies, and server all work together before adding real functionality.
2. **Isolate dependencies from day one.** Using a virtual environment from the very first commit avoids version conflicts later and keeps the project self-contained.
3. **Declare dependencies for future needs early when known.** Adding `pdfplumber` up front — before any PDF-parsing code existed — meant the environment was already ready when that work began.
4. **Verify by running, not by reading.** Actually starting the server and checking the response confirmed the setup worked, catching anything a code review alone might miss.
