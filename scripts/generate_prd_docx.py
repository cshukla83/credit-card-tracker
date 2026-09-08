"""Render docs/PRD.docx from docs/PRD.md.

Run from the project root, with the venv active:
    python3 -m scripts.generate_prd_docx

Optional arguments:
    --source docs/PRD.md    input markdown
    --out    docs/PRD.docx  output Word document

The markdown file is the single source of truth: this script reads it and
renders it, rather than carrying its own copy of the PRD content. Keeping the
text in one place is deliberate -- two hand-maintained copies of the same
document drift apart silently, and a Word file gives no diff to notice it in.

Requires python-docx, which is listed in requirements.txt but is NOT used by
the tracker itself -- only by this script.

Only the subset of markdown the PRD actually uses is supported: headings,
paragraphs, bullet and numbered lists, pipe tables, and inline bold/code.
Anything else is emitted as plain text rather than silently dropped.
"""

from __future__ import annotations

import argparse
import re
import sys

try:
    from docx import Document
    from docx.shared import Pt
except ModuleNotFoundError:  # pragma: no cover - environment-dependent
    sys.exit(
        "python-docx is not installed. Install it with:\n"
        "    pip install -r requirements.txt\n"
        "It is needed only for PRD export, not for running the app."
    )

DEFAULT_SOURCE = "docs/PRD.md"
DEFAULT_OUT = "docs/PRD.docx"

# Inline spans: **bold** or `code`. Captured with a single alternation so the
# text is split in one pass and the delimiters stay attached to their content.
_INLINE_RE = re.compile(r"(\*\*.+?\*\*|`[^`]+`)")

_BULLET_RE = re.compile(r"^[-*]\s+(?P<text>.*)$")
_NUMBERED_RE = re.compile(r"^\d+\.\s+(?P<text>.*)$")
_HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<text>.*)$")
# A table separator row, e.g. "|---|---|" or "| :--- | ---: |".
_TABLE_SEPARATOR_RE = re.compile(r"^\|[\s:|-]+\|$")


def _add_inline(paragraph, text: str) -> None:
    """Append text to a paragraph, honouring **bold** and `code` spans."""
    for part in _INLINE_RE.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            paragraph.add_run(part[2:-2]).bold = True
        elif part.startswith("`") and part.endswith("`"):
            run = paragraph.add_run(part[1:-1])
            run.font.name = "Consolas"
            run.font.size = Pt(9.5)
        else:
            paragraph.add_run(part)


def _split_row(line: str) -> "list[str]":
    """Split a markdown pipe-table row into cell texts."""
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _add_table(document, rows: "list[list[str]]") -> None:
    """Render collected rows as a real Word table, first row as the header."""
    header, *body = rows
    table = document.add_table(rows=1, cols=len(header))
    table.style = "Table Grid"

    for cell, text in zip(table.rows[0].cells, header):
        cell.text = ""
        paragraph = cell.paragraphs[0]
        _add_inline(paragraph, text)
        for run in paragraph.runs:
            run.bold = True

    for row in body:
        cells = table.add_row().cells
        # Pad or trim so a malformed row can't raise or silently lose cells.
        for cell, text in zip(cells, list(row) + [""] * (len(header) - len(row))):
            cell.text = ""
            _add_inline(cell.paragraphs[0], text)


def _flush_paragraph(document, buffer: "list[str]") -> None:
    """Emit buffered soft-wrapped lines as one paragraph."""
    if not buffer:
        return
    _add_inline(document.add_paragraph(), " ".join(buffer))
    buffer.clear()


def render(markdown: str) -> "Document":
    document = Document()
    lines = markdown.splitlines()
    buffer: list[str] = []
    index = 0

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        # --- table block ---------------------------------------------------
        if (
            stripped.startswith("|")
            and index + 1 < len(lines)
            and _TABLE_SEPARATOR_RE.match(lines[index + 1].strip())
        ):
            _flush_paragraph(document, buffer)
            rows = [_split_row(stripped)]
            index += 2  # skip the header and the separator
            while index < len(lines) and lines[index].strip().startswith("|"):
                rows.append(_split_row(lines[index].strip()))
                index += 1
            _add_table(document, rows)
            document.add_paragraph()
            continue

        # --- blank line ------------------------------------------------------
        if not stripped:
            _flush_paragraph(document, buffer)
            index += 1
            continue

        # --- heading ---------------------------------------------------------
        heading = _HEADING_RE.match(stripped)
        if heading:
            _flush_paragraph(document, buffer)
            depth = len(heading.group("hashes"))
            text = heading.group("text")
            if depth == 1:
                # The document's own title line.
                document.add_heading(text, level=0)
            else:
                # "##" -> Heading 1, "###" -> Heading 2, matching the source's
                # section/subsection levels.
                document.add_heading(text, level=depth - 1)
            index += 1
            continue

        # --- list items ------------------------------------------------------
        bullet = _BULLET_RE.match(stripped)
        if bullet:
            _flush_paragraph(document, buffer)
            _add_inline(document.add_paragraph(style="List Bullet"), bullet.group("text"))
            index += 1
            continue

        numbered = _NUMBERED_RE.match(stripped)
        if numbered:
            _flush_paragraph(document, buffer)
            _add_inline(document.add_paragraph(style="List Number"), numbered.group("text"))
            index += 1
            continue

        # --- ordinary prose (soft-wrapped across lines) -----------------------
        buffer.append(stripped)
        index += 1

    _flush_paragraph(document, buffer)
    return document


def main() -> None:
    parser = argparse.ArgumentParser(description="Render docs/PRD.docx from docs/PRD.md.")
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--out", default=DEFAULT_OUT)
    args = parser.parse_args()

    try:
        with open(args.source) as handle:
            markdown = handle.read()
    except FileNotFoundError:
        sys.exit(f"Error: source file not found: {args.source}")

    render(markdown).save(args.out)
    print(f"Wrote {args.out} from {args.source}")


if __name__ == "__main__":
    main()
