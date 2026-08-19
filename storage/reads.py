import sqlite3

from storage.dates import to_date_str


def get_transactions(
    conn: sqlite3.Connection,
    card_id: "int | None" = None,
    start_date=None,
    end_date=None,
) -> "list[dict]":
    """Query transactions, optionally filtered by card and/or date range.

    All three filters are optional and compose with AND. card_id filters via
    the parent statement's card_id (transactions don't store card_id
    directly, so this JOINs through statements). start_date/end_date filter
    on transactions.txn_date and are both inclusive. Accepts date objects or
    ISO strings for start_date/end_date.

    Results are ordered most-recent-first (txn_date DESC), with id DESC as a
    stable tiebreaker for multiple transactions on the same date.
    """
    query = "SELECT transactions.* FROM transactions"
    conditions = []
    params = []

    if card_id is not None:
        query += " JOIN statements ON transactions.statement_id = statements.id"
        conditions.append("statements.card_id = ?")
        params.append(card_id)

    if start_date is not None:
        conditions.append("transactions.txn_date >= ?")
        params.append(to_date_str(start_date))

    if end_date is not None:
        conditions.append("transactions.txn_date <= ?")
        params.append(to_date_str(end_date))

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY transactions.txn_date DESC, transactions.id DESC"

    rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]
