from __future__ import annotations

from parsers.base import ParsedStatement


def parse(pdf_path: str, password: str, card_type: str) -> ParsedStatement:
    """Route parsing to the IndusInd parser for the given card_type.

    card_type matching is case-insensitive: "legend", "LEGEND", and "Legend"
    all route to the same parser. The normalized (title-case) form is what's
    actually compared and reported in the NotImplementedError message.
    """
    normalized = card_type.strip().title()

    if normalized == "Legend":
        # Imported here rather than at module load time, so a broken
        # card-type-specific parser (import error, etc.) doesn't prevent
        # dispatch from working for other card types.
        from parsers.indusind import indusind_legend

        return indusind_legend.parse(pdf_path, password)

    raise NotImplementedError(f"IndusInd {card_type} parser not yet implemented")
