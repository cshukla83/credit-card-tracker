import sqlite3

from storage.dates import to_date_str
from storage.normalize import normalize_label

# Label filters (category, subcategory, merchant) accept this value to mean
# "rows where that label is NULL" -- the deliberate inverse of the
# aggregation output's NULL -> "Uncategorized" folding, so a value copied
# from a dashboard bucket back into a filter selects exactly that bucket.
UNCATEGORIZED_FILTER = "Uncategorized"

# review_status (Session 80): the one predicate no single-column filter can
# express -- a row's labelling is "complete" only when all three labels are
# set, "incomplete" when any is missing.
REVIEW_STATUSES = ("incomplete", "complete")


class ReviewStatusError(ValueError):
    """An invalid review_status value (the API maps it to 422)."""

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
    category: "str | None" = None,
    subcategory: "str | None" = None,
    merchant: "str | None" = None,
    review_status: "str | None" = None,
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
      card_id, statement_month              -> statements
      bank, card_type                       -> cards
      start_date, end_date                  -> transactions
      category, subcategory, merchant       -> transactions (Session 74)
    Intermediate tables on the way from `anchor` are joined too, so a cards
    query with a date range walks cards -> statements -> transactions.

    The three label filters are normalised with the same Title Case rule
    the write path applies (so "food" matches "Food"), are independently
    combinable with each other and with every other filter, and treat the
    value "Uncategorized" as `IS NULL` (see UNCATEGORIZED_FILTER). An
    empty or whitespace-only value is ignored, as if not given.

    review_status (Session 80): "incomplete" -> category IS NULL OR
    subcategory IS NULL OR merchant IS NULL; "complete" -> all three IS
    NOT NULL. Any other value raises ReviewStatusError. Combinable with
    everything, including the label filters (e.g. category=Food &
    review_status=incomplete: Food rows still missing a subcategory or
    merchant).

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
    for column, raw in (("category", category), ("subcategory", subcategory), ("merchant", merchant)):
        if raw is None or not raw.strip():
            continue
        needed.add("transactions")
        value = normalize_label(raw)
        if value == UNCATEGORIZED_FILTER:
            # "Uncategorized" is never stored (NULL is the only "unset"), so
            # the filter selects the NULL rows -- the inverse of the folding
            # aggregation applies on output.
            conditions.append(f"transactions.{column} IS NULL")
        else:
            conditions.append(f"transactions.{column} = ?")
            params.append(value)
    if review_status is not None:
        if review_status not in REVIEW_STATUSES:
            raise ReviewStatusError(
                f"review_status must be one of {', '.join(REVIEW_STATUSES)}; got {review_status!r}"
            )
        needed.add("transactions")
        if review_status == "incomplete":
            conditions.append(
                "(transactions.category IS NULL OR transactions.subcategory IS NULL "
                "OR transactions.merchant IS NULL)"
            )
        else:
            conditions.append(
                "(transactions.category IS NOT NULL AND transactions.subcategory IS NOT NULL "
                "AND transactions.merchant IS NOT NULL)"
            )

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
    category: "str | None" = None,
    subcategory: "str | None" = None,
    merchant: "str | None" = None,
    review_status: "str | None" = None,
) -> "list[dict]":
    """Query transactions, optionally filtered by card, date range, statement
    month, bank, card type, and/or the three labels (Session 75; label
    filters follow filter_sql's rules -- normalised, "Uncategorized" = NULL).

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
        category=category,
        subcategory=subcategory,
        merchant=merchant,
        review_status=review_status,
        always_join=("statements", "cards"),
    )
    return _select_transactions(conn, joins, where, params)


def _select_transactions(conn, joins, where, params, limit=None, offset=0) -> "list[dict]":
    # The one row query behind get_transactions and get_transactions_page,
    # so the columns and the order can never drift apart between the two.
    sql = (
        "SELECT transactions.*, statements.card_id AS card_id, cards.bank AS bank "
        "FROM transactions"
        + joins
        + where
        + " ORDER BY transactions.txn_date DESC, transactions.id DESC"
    )
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params = [*params, limit, offset]
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


# Page size for the paged form of GET /transactions (the dashboard's
# drill-down list). Fixed, not a request parameter.
TRANSACTIONS_PAGE_SIZE = 25


def get_transactions_page(
    conn: sqlite3.Connection,
    page: int,
    card_id: "int | None" = None,
    start_date=None,
    end_date=None,
    statement_month: "str | None" = None,
    bank: "str | None" = None,
    card_type: "str | None" = None,
    category: "str | None" = None,
    subcategory: "str | None" = None,
    merchant: "str | None" = None,
    review_status: "str | None" = None,
) -> dict:
    """One page of get_transactions' result, plus the total across all pages.

    Same filters, same row selection (every debit and credit, payments
    included), same order as get_transactions -- page N is exactly rows
    (N-1)*25 .. N*25-1 of the unpaged list. `page` is 1-based; a page past
    the end returns an empty `transactions` with the true `total`.

    Returns {"transactions": [...], "total": n, "page": page,
    "page_size": TRANSACTIONS_PAGE_SIZE}.
    """
    if page < 1:
        raise ValueError(f"page must be >= 1; got {page}")
    joins, where, params = filter_sql(
        "transactions",
        card_id=card_id,
        statement_month=statement_month,
        bank=bank,
        card_type=card_type,
        start_date=start_date,
        end_date=end_date,
        category=category,
        subcategory=subcategory,
        merchant=merchant,
        review_status=review_status,
        always_join=("statements", "cards"),
    )
    total = conn.execute("SELECT COUNT(*) FROM transactions" + joins + where, params).fetchone()[0]
    rows = _select_transactions(
        conn, joins, where, params,
        limit=TRANSACTIONS_PAGE_SIZE, offset=(page - 1) * TRANSACTIONS_PAGE_SIZE,
    )
    return {"transactions": rows, "total": total, "page": page, "page_size": TRANSACTIONS_PAGE_SIZE}


def list_statement_months(
    conn: sqlite3.Connection,
    card_id: "int | None" = None,
    bank: "str | None" = None,
    card_type: "str | None" = None,
    start_date=None,
    end_date=None,
    category: "str | None" = None,
    subcategory: "str | None" = None,
    merchant: "str | None" = None,
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
        category=category,
        subcategory=subcategory,
        merchant=merchant,
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
    category: "str | None" = None,
    subcategory: "str | None" = None,
    merchant: "str | None" = None,
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
        category=category,
        subcategory=subcategory,
        merchant=merchant,
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


def find_statement(conn: sqlite3.Connection, card_id: int, period_start, period_end) -> "dict | None":
    """The statement already imported for this (card_id, period_start, period_end), or None.

    The same key insert_statement()'s UNIQUE dedup skips on -- read here
    ahead of time (Session 98's upload preview) so a duplicate can be
    reported before anything is parsed further, instead of surfacing as a
    silent no-op at write time.
    """
    row = conn.execute(
        "SELECT * FROM statements WHERE card_id = ? AND period_start = ? AND period_end = ?",
        (card_id, to_date_str(period_start), to_date_str(period_end)),
    ).fetchone()
    return dict(row) if row is not None else None
