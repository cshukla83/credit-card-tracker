"""Bank detection for an uploaded statement PDF (Session 97).

Two steps, kept separate because they fail differently:

  unlock(pdf_path)   open the PDF and read its first page. Every sample
                     statement this project has seen is password-protected
                     (checked: all 18 local samples refuse to open without
                     one), so identification cannot happen before a
                     password is found. The file is tried without a
                     password first, then with each bank's .env password in
                     registry order; the first that opens wins. Which
                     password opened it says nothing about the bank -- the
                     text does (a user could keep the same password for two
                     banks) -- so the result carries the password only so
                     the parse step can reuse it.

  identify(text)     match the registry's per-bank landmark against that
                     text. Exactly one bank must match; zero or several
                     means the format is not recognized.

Nothing here parses transactions; that stays with each bank's parser.
"""

from __future__ import annotations

import os
from typing import NamedTuple

import pdfplumber
import re
from dotenv import load_dotenv
from pdfminer.pdfdocument import PDFPasswordIncorrect
from pdfplumber.utils.exceptions import PdfminerException

from parsers.registry import BANKS

load_dotenv()


class PasswordNeededError(Exception):
    """The PDF is encrypted and no password on file opens it."""

    def __init__(self, tried_env_keys: "list[str]"):
        self.tried_env_keys = tried_env_keys
        super().__init__("No password in .env opens this PDF")


class NotAPdfError(Exception):
    """pdfplumber could not read the file for a reason other than a password."""


class Unlocked(NamedTuple):
    password: "str | None"  # None when the file opened without one
    first_page_text: str


def _first_page_text(pdf_path: str, password: "str | None") -> str:
    with pdfplumber.open(pdf_path, password=password) as pdf:
        return pdf.pages[0].extract_text() or ""


def _is_password_error(exc: PdfminerException) -> bool:
    # pdfplumber wraps every pdfminer failure as PdfminerException(original);
    # the original is args[0]. A wrong/missing password is the one case a
    # different password can fix, so it is the one told apart here.
    return bool(exc.args) and isinstance(exc.args[0], PDFPasswordIncorrect)


PASSWORD_KEY_SUFFIX = "_SAMPLE_PASSWORD"


def candidate_passwords() -> "list[tuple[str, str]]":
    """(env key, password) for every non-empty environment variable named
    *_SAMPLE_PASSWORD, alphabetically by key.

    Convention-based since Session 111, not a maintained list: the four
    registry banks' keys follow this shape and are still tried exactly as
    before, and a key for a bank with no parser (say AXIS_SAMPLE_PASSWORD)
    is tried too -- that is what lets a locked statement from an unknown
    bank decrypt far enough to be reported as unrecognized and offered the
    best-attempt / LLM readers. The accepted trade-off: anything else in
    the environment with that suffix is also tried as a PDF password. The
    order does not affect the outcome -- the bank is decided from the text,
    never from which key opened the file -- it is fixed only so tests can
    assert it.
    """
    return sorted(
        (key, value)
        for key, value in os.environ.items()
        if key.endswith(PASSWORD_KEY_SUFFIX) and value
    )


def unlock(pdf_path: str) -> Unlocked:
    attempts: "list[str | None]" = [None] + [pw for _, pw in candidate_passwords()]
    for password in attempts:
        try:
            return Unlocked(password=password, first_page_text=_first_page_text(pdf_path, password))
        except PdfminerException as e:
            if _is_password_error(e):
                continue
            raise NotAPdfError(str(e.args[0]) if e.args else str(e)) from e
    raise PasswordNeededError([key for key, _ in candidate_passwords()])


def identify(text: str) -> "tuple[str, str] | None":
    """(bank, card_type) for the one bank whose landmark appears in `text`, else None."""
    matches = [
        (name, bank.card_type)
        for name, bank in BANKS.items()
        if re.search(bank.landmark, text, re.IGNORECASE)
    ]
    return matches[0] if len(matches) == 1 else None
