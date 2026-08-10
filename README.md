# Project Name

One or two sentences: what does this project do, and why did you build it?

## Prerequisites

- [Claude Code](https://claude.com/product/claude-code) must be installed and set up
- Python 3.x installed
- (Add any other tools/accounts needed, e.g. an API key)

## What this project does

A slightly longer explanation for a visitor with no context — what problem it solves,
what the end result looks like (screenshot/GIF if possible once built).

## Project structure

```
project-name/
├── main.py              # entry point
├── requirements.txt      # Python dependencies
├── venv/                 # local virtual environment (not tracked in git)
├── docs/
│   └── DEVLOG.md         # detailed, step-by-step build log
└── README.md             # this file
```

## Setup

```bash
git clone <repo-url>
cd project-name
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Running the app

```bash
source venv/bin/activate
uvicorn main:app --reload
```

Then open http://127.0.0.1:8000/ in your browser.

## Learning notes

This project was built while learning Claude Code hands-on. The full session-by-session
build log — including every command run and what it means — is in
[`docs/DEVLOG.md`](docs/DEVLOG.md).

## Status

🚧 In progress — last updated: <date>
