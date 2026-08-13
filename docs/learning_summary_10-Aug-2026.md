# Learning Summary — 10 Aug 2026

## What We Achieved
- Initialized git for the project with a correctly working `.gitignore`, and made the first commit.
- Set up secure handling of the sample statement's password: added `python-dotenv`, stored the password in a git-ignored `.env` file, and verified the full chain — `.env` → `python-dotenv` → `pdfplumber` — could decrypt and read the sample PDF.
- Found and fixed a real secret-handling mistake: a password was accidentally written in plaintext into the project log and committed to git history.

## How We Achieved It
- Fixed pre-existing setup issues before committing anything, rather than working around them — a `.gitignore` file with the wrong filename (so git silently ignored nothing), a misplaced log file, and a misnamed data folder.
- Verified `.gitignore` was actually working by checking `git status` before every commit, instead of just trusting the file's contents.
- Kept the real password out of chat and prompts — set directly in `.env` by hand — except for one instance where it was included in a prompt. Because the project log quotes prompts verbatim, that password got copied into the log and committed.
- Once caught, rewrote the affected commit with `git commit --amend` and verified the password was gone from the *entire* git history (`git log --all -p`), not just the latest commit or working tree.

## Key Learnings
1. **Verify tooling actually works — don't assume.** A `.gitignore` file with the wrong filename does nothing, silently.
2. **`git status` before committing is a cheap, reliable safety check** for catching anything that shouldn't be staged.
3. **Never put a secret inside a prompt that will be logged verbatim** — even a single occurrence gets captured in the log and, if committed, in git history.
4. **Removing a leaked secret needs a full-history check**, not just amending the latest commit — `git log --all -p` confirms it's gone everywhere, not just the tip.
5. **Describe the action, not the value.** Phrasing a prompt as "update `.env` with the password" instead of including the password itself avoids the whole problem.
