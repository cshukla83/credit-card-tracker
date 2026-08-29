from datetime import date, datetime

# Parser transaction field name -> storage transaction field name. "date" is
# deliberately left out of this map: it needs a type conversion (datetime ->
# date), not just a rename, so it's handled explicitly in _map_transaction()
# instead of being folded into this table.
_FIELD_MAP = {
    "description": "description",
    "amount": "amount",
    "type": "txn_type",
    "reward_points": "reward_points",
}


def _map_transaction(txn: dict) -> dict:
    mapped = {storage_key: txn[parser_key] for parser_key, storage_key in _FIELD_MAP.items()}

    txn_date = txn["date"]
    # The parser's "date" field is a full datetime (it carries time-of-day for
    # some statement layouts); storage's txn_date column is a pure date, so
    # the time component is dropped here rather than silently stored inside a
    # DATE column via isoformat()'s full datetime string.
    mapped["txn_date"] = txn_date.date() if isinstance(txn_date, datetime) else txn_date

    return mapped


def from_parsed_statement(parsed: dict, card_id: int) -> "tuple[int, date, date, list[dict]]":
    """Adapt any dispatch-layer ParsedStatement into insert_statement()'s argument shape.

    Bank-agnostic by construction: every parser returns the same
    parsers.base.ParsedStatement shape, so this reads only the field names in
    that contract and never branches on which bank produced the statement.
    Verified against HDFC and ICICI in Session 30 -- the rename from from_hdfc()
    was the only change needed.

    card_id is looked up by the caller (e.g. the CLI) before calling this --
    this adapter never touches the cards table itself.
    """
    transactions = [_map_transaction(txn) for txn in parsed["transactions"]]
    return card_id, parsed["period_start"], parsed["period_end"], transactions
