import os

import pdfplumber
from dotenv import load_dotenv

load_dotenv()

password = os.environ["ICICI_SAMPLE_PASSWORD"]
pdf_path = "data/statements/icici_sample.pdf"
output_path = "data/exploration_output_icici.txt"

lines = []

with pdfplumber.open(pdf_path, password=password) as pdf:
    for i, page in enumerate(pdf.pages, start=1):
        lines.append(f"===== PAGE {i} — raw text =====")
        lines.append(page.extract_text() or "(no text extracted)")
        lines.append("")

        lines.append(f"===== PAGE {i} — extract_table() =====")
        table = page.extract_table()
        lines.append(repr(table) if table else "(no table found)")
        lines.append("")

        lines.append(f"===== PAGE {i} — extract_tables() =====")
        tables = page.extract_tables()
        if tables:
            for j, t in enumerate(tables, start=1):
                lines.append(f"-- table {j} --")
                lines.append(repr(t))
        else:
            lines.append("(no tables found)")
        lines.append("")

os.makedirs(os.path.dirname(output_path), exist_ok=True)
with open(output_path, "w") as f:
    f.write("\n".join(lines))

print(f"Wrote exploration output to {output_path}")
