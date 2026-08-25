import sqlite3

from storage.dates import to_date_str


def get_transactions(
    conn: sqlite3.Connection,
    card_id: "int | None" = None,
    start_date=None,
    end_date=None,
    statement_month: "str | None" = None,
    bank: "str | None" = None,
    card_type: "str | None" = None,
) -> "list[dict]":
    """Query transactions, optionally filtered by card, date range, statement
    month, bank, and/or card type.

    All filters are optional and compose with AND. card_id, statement_month,
    bank, and card_type all filter via the parent statement (and, for bank/
    card_type, the grandparent card) rather than columns on transactions
    itself, so the statements/cards JOINs are only added when a filter that
    actually needs them is present -- never unconditionally. start_date/
    end_date filter on transactions.txn_date and are both inclusive. Accepts
    date objects or ISO strings for start_date/end_date.

    Results are ordered most-recent-first (txn_date DESC), with id DESC as a
    stable tiebreaker for multiple transactions on the same date.
    """
    query = "SELECT transactions.* FROM transactions"
    conditions = []
    params = []

    needs_statements = (
        card_id is not None
        or statement_month is not None
        or bank is not None
        or card_type is not None
    )
    needs_cards = bank is not None or card_type is not None

    if needs_statements:
        query += " JOIN statements ON transactions.statement_id = statements.id"
    if needs_cards:
        query += " JOIN cards ON statements.card_id = cards.id"

    if card_id is not None:
        conditions.append("statements.card_id = ?")
        params.append(card_id)

    if statement_month is not None:
        conditions.append("statements.statement_month = ?")
        params.append(statement_month)

    if bank is not None:
        conditions.append("cards.bank = ?")
        params.append(bank)

    if card_type is not None:
        conditions.append("cards.card_type = ?")
        params.append(card_type)

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


def list_statement_months(conn: sqlite3.Connection) -> "list[str]":
    """Distinct statement_month values, most recent first.

    Ordered by MAX(period_end) DESC per group, not alphabetically --
    alphabetical order would put "January-2026" before "December-2025" even
    though January-2026 is the more recent month, since 'J' < 'D' lexically
    has nothing to do with chronology across a year boundary.
    """
    rows = conn.execute(
        "SELECT statement_month FROM statements "
        "GROUP BY statement_month "
        "ORDER BY MAX(period_end) DESC"
    ).fetchall()
    return [row["statement_month"] for row in rows]


def list_card_types(conn: sqlite3.Connection) -> "list[dict]":
    """Distinct (bank, card_type) pairs for cards with at least one statement.

    Same "only cards with statements" filter as
    storage.cards.list_cards_with_statements(), applied here instead since
    this groups by bank/card_type rather than returning full card rows.
    Ordered bank ASC, then card_type ASC.
    """
    rows = conn.execute(
        "SELECT DISTINCT cards.bank, cards.card_type FROM cards "
        "JOIN statements ON statements.card_id = cards.id "
        "ORDER BY cards.bank ASC, cards.card_type ASC"
    ).fetchall()
    return [{"bank": row["bank"], "card_type": row["card_type"]} for row in rows]
