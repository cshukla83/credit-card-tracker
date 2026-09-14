from __future__ import annotations

from parsers.base import ParsedStatement


def parse(pdf_path: str, password: str, card_type: str) -> ParsedStatement:
    """Route parsing to the HDFC parser for the given card_type.

    card_type matching is case-insensitive: "diners", "DINERS", and "Diners"
    all route to the same parser. The normalized (title-case) form is what's
    actually compared and reported in the NotImplementedError message.
    """
    normalized = card_type.strip().title()

    if normalized == "Diners":
        # Imported here rather than at module load time, so a broken
        # card-type-specific parser (import error, etc.) doesn't prevent
        # dispatch from working for other card types.
        from parsers import hdfc_diners

        return hdfc_diners.parse(pdf_path, password)

    raise NotImplementedError(f"HDFC {card_type} parser not yet implemented")


def extract_summary(pdf_path: str, password: str, card_type: str) -> dict:
    """Route the page-1 summary-box extraction the same way parse() routes parsing.

    The summary is the reconciliation side of an import (Session 98's upload
    preview checks parsed debit/credit sums against it), so it needs the same
    card_type routing as parse() rather than a direct import of one module.
    """
    normalized = card_type.strip().title()

    if normalized == "Diners":
        from parsers import hdfc_diners

        return hdfc_diners.extract_summary(pdf_path, password)

    raise NotImplementedError(f"HDFC {card_type} parser not yet implemented")
