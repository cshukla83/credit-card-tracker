"""Shared test helpers (Session 97).

`make_pdf` builds a small, valid, unencrypted single-page PDF from a list of
text lines, so the upload endpoints can be tested end to end -- multipart in,
pdfplumber text extraction, bank landmark, parser -- without the real
(git-ignored, password-protected) sample statements. Helvetica, one line per
text row, correct xref table; pdfplumber's extract_text() returns the lines
joined with newlines, which is exactly the shape the parsers' regexes expect.
"""

import io

import pytest


def _pdf_string(text: str) -> str:
    return "(" + text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ")"


def build_pdf(lines: "list[str]") -> bytes:
    content = (
        "BT /F1 11 Tf 40 780 Td 14 TL "
        + " ".join(_pdf_string(line) + " Tj T*" for line in lines)
        + " ET"
    )
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n{body}\nendobj\n".encode("latin-1"))
    xref_at = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF\n".encode()
    )
    return out.getvalue()


@pytest.fixture
def make_pdf():
    return build_pdf
