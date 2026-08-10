import os

import pdfplumber
from dotenv import load_dotenv

load_dotenv()

password = os.environ["HDFC_SAMPLE_PASSWORD"]
pdf_path = "data/statements/hdfc_sample.pdf"

with pdfplumber.open(pdf_path, password=password) as pdf:
    first_page = pdf.pages[0]
    print(first_page.extract_text())
