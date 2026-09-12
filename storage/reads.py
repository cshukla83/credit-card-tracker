import sqlite3

from storage.dates import to_date_str

# The three tables form a chain: cards -(card_id)- statements -(statement_id)-
# transactions. Every read-path filter lives on exactly one of them, and a
# query anchored on any one table reaches the others by walking the chain.
_CHAIN = ("cards", "statements", "transactions")
_JOIN_SQL = {
    ("cards", "statements"): "JOIN statements ON statements.card_id = cards.id",
    ("statements", "cards"): "JOIN cards ON statements.card_id = cards.id",
    ("statements", "transactions"): "JOIN transactions ON transactions.statement_id = statements.id",
    ("transactions", "statements"): "JOIN statements ON transactions.statement_id = statements.id",
}


def filter_sql(
    anchor: str,
    *,
    card_id: "int | None" = None,
    statement_month: "str | None" = None,
    bank: "str | None" = None,
    card_type: "str | None" = None,
    start_date=None,
    end_date=None,
    always_join: "tuple[str, ...]" = (),
) -> "tuple[str, str, list]":
    """Build the JOIN and WHERE clauses that narrow `anchor` by the given filters.

    Returns (joins_sql, where_sql, params). `joins_sql` contains only the
    JOINs the active filters actually need -- never an unconditional walk of
    the whole chain -- plus any in `always_join` (a listing that is defined
    as "cards with at least one statement" passes ("statements",)). Filters
    compose with AND. start_date/end_date are inclusive and accept date
    objects or ISO strings.

    Which table each filter needs:
      card_id, statement_month  -> statements
      bank, card_type           -> cards
      start_date, end_date      -> transactions
    Intermediate tables on the way from `anchor` are joined too, so a cards
    query with a date range walks cards -> statements -> transactions.

    This is the single definition of the read-path filters; get_transactions
    and the three listing functions all use it, so "narrow by X" means the
    same thing on every endpoint.
    """
    needed = set(always_join)
    conditions = []
    params = []

    if card_id is not None:
        needed.add("statements")
        conditions.append("statements.card_id = ?")
        params.append(card_id)
    if statement_month is not None:
        needed.add("statements")
        conditions.append("statements.statement_month = ?")
        params.append(statement_month)
    if bank is not None:
        needed.add("cards")
        conditions.append("cards.bank = ?")
        params.append(bank)
    if card_type is not None:
        needed.add("cards")
        conditions.append("cards.card_type = ?")
        params.append(card_type)
    if start_date is not None:
        needed.add("transactions")
        conditions.append("transactions.txn_date >= ?")
        params.append(to_date_str(start_date))
    if end_date is not None:
        needed.add("transactions")
        conditions.append("transactions.txn_date <= ?")
        params.append(to_date_str(end_date))

    # Walk outward from the anchor in each direction along the chain, adding
    # a JOIN for every step until the farthest needed table in that
    # direction is reached. Intermediate tables come along for free.
    joins = []
    anchor_pos = _CHAIN.index(anchor)
    needed.discard(anchor)
    for step in (-1, 1):
        positions = [
            _CHAIN.index(t)
            for t in needed
            if (_CHAIN.index(t) - anchor_pos) * step > 0
        ]
        if not positions:
            continue
        farthest = max(positions, key=lambda p: abs(p - anchor_pos))
        current = anchor_pos
        while current != farthest:
            joins.append(_JOIN_SQL[(_CHAIN[current], _CHAIN[current + step])])
            current += step

    joins_sql = (" " + " ".join(joins)) if joins else ""
    where_sql = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    return joins_sql, where_sql, params


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

    Every row carries, besides `transactions.*`, the two identity columns a
    consumer otherwise cannot derive: `card_id` (from statements) and `bank`
    (from cards) -- added in Session 63 so the frontend can name a row's
    bank without a second request. That makes the statements and cards
    JOINs unconditional *for this query*: they are needed for the output,
    not only for filtering. The filter set itself is still the shared
    `filter_sql`, and the listing queries still join only what their
    filters need. Explicit `transactions.*` plus named columns, never a bare
    `*`, so the three tables' `id` columns cannot collide.

    All filters are optional and compose with AND. card_id, statement_month,
    bank, and card_type filter via the parent statement / grandparent card;
    start_date/end_date filter on transactions.txn_date and are both
    inclusive. Accepts date objects or ISO strings for start_date/end_date.

    Results are ordered most-recent-first (txn_date DESC), with id DESC as a
    stable tiebreaker for multiple transactions on the same date.
    """
    joins, where, params = filter_sql(
        "transactions",
        card_id=card_id,
        statement_month=statement_month,
        bank=bank,
        card_type=card_type,
        start_date=start_date,
        end_date=end_date,
        always_join=("statements", "cards"),
    )
    rows = conn.execute(
        "SELECT transactions.*, statements.card_id AS card_id, cards.bank AS bank "
        "FROM transactions"
        + joins
        + where
        + " ORDER BY transactions.txn_date DESC, transactions.id DESC",
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def list_statement_months(
    conn: sqlite3.Connection,
    card_id: "int | None" = None,
    bank: "str | None" = None,
    card_type: "str | None" = None,
    start_date=None,
    end_date=None,
) -> "list[str]":
    """Distinct statement_month values, most recent first, optionally narrowed.

    Ordered by MAX(period_end) DESC per group, not alphabetically --
    alphabetical order would put "January-2026" before "December-2025" even
    though January-2026 is the more recent month, since 'J' < 'D' lexically
    has nothing to do with chronology across a year boundary.

    With a date range, a month is listed if any of its statements has at
    least one transaction in the range (the transactions JOIN is added only
    then). card_id/bank/card_type narrow to that card's months. There is no
    statement_month parameter: a filter is never narrowed by itself.
    """
    joins, where, params = filter_sql(
        "statements",
        card_id=card_id,
        bank=bank,
        card_type=card_type,
        start_date=start_date,
        end_date=end_date,
    )
    rows = conn.execute(
        "SELECT statements.statement_month FROM statements"
        + joins
        + where
        + " GROUP BY statements.statement_month"
        + " ORDER BY MAX(statements.period_end) DESC",
        params,
    ).fetchall()
    return [row["statement_month"] for row in rows]


def list_card_types(
    conn: sqlite3.Connection,
    card_id: "int | None" = None,
    statement_month: "str | None" = None,
    bank: "str | None" = None,
    start_date=None,
    end_date=None,
) -> "list[dict]":
    """Distinct (bank, card_type) pairs for cards with at least one statement,
    optionally narrowed. Ordered bank ASC, then card_type ASC.

    Same "only cards with statements" rule as
    storage.cards.list_cards_with_statements(), expressed as an always-on
    statements JOIN. A date range additionally requires a transaction in the
    range. `bank` is accepted so a frontend can list the card types within
    one bank; there is no card_type parameter -- a filter is never narrowed
    by itself.
    """
    joins, where, params = filter_sql(
        "cards",
        card_id=card_id,
        statement_month=statement_month,
        bank=bank,
        start_date=start_date,
        end_date=end_date,
        always_join=("statements",),
    )
    rows = conn.execute(
        "SELECT DISTINCT cards.bank, cards.card_type FROM cards"
        + joins
        + where
        + " ORDER BY cards.bank ASC, cards.card_type ASC",
        params,
    ).fetchall()
    return [{"bank": row["bank"], "card_type": row["card_type"]} for row in rows]
