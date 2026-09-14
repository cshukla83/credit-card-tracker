import sqlite3


class CardAlreadyExistsError(Exception):
    """Raised when create_card() collides with the (bank, card_type, nickname) UNIQUE constraint.

    Card creation is an explicit user action, so a collision here is treated
    as a user-facing error rather than a silent skip (unlike insert_statement(),
    where a dedup collision during bulk import is the expected, correct outcome).
    """


def insert_card_row(
    conn: sqlite3.Connection, bank: str, card_type: str, nickname: "str | None" = None
) -> int:
    """The INSERT alone, inside whatever transaction the caller holds.

    Split out of create_card() in Session 112 so the upload confirm can
    create a card and its first statement as one atomic write
    (storage.writes.insert_statement_with_new_card) without a second copy
    of this statement or its collision rule.
    """
    try:
        cursor = conn.execute(
            "INSERT INTO cards (bank, card_type, nickname) VALUES (?, ?, ?)",
            (bank, card_type, nickname),
        )
    except sqlite3.IntegrityError as e:
        raise CardAlreadyExistsError(
            f"Card already exists: bank={bank!r}, card_type={card_type!r}, nickname={nickname!r}"
        ) from e
    return cursor.lastrowid


def create_card(
    conn: sqlite3.Connection, bank: str, card_type: str, nickname: "str | None" = None
) -> int:
    with conn:
        return insert_card_row(conn, bank, card_type, nickname)


def get_card(conn: sqlite3.Connection, card_id: int) -> "dict | None":
    row = conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
    return dict(row) if row is not None else None


def find_card(
    conn: sqlite3.Connection, bank: str, card_type: str, nickname: "str | None" = None
) -> "dict | None":
    # SQLite's "= ?" never matches when the bound parameter is NULL, so a
    # nickname of None needs an explicit "IS NULL" to find rows where the
    # nickname column is actually unset -- otherwise this would always miss.
    if nickname is None:
        row = conn.execute(
            "SELECT * FROM cards WHERE bank = ? AND card_type = ? AND nickname IS NULL",
            (bank, card_type),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM cards WHERE bank = ? AND card_type = ? AND nickname = ?",
            (bank, card_type, nickname),
        ).fetchone()
    return dict(row) if row is not None else None


def find_cards_for_type(conn: sqlite3.Connection, bank: str, card_type: str) -> "list[dict]":
    """Every card of one (bank, card_type), each with its most recent statement period.

    Used by upload detection (Session 97) to resolve a detected bank/card
    type to a card row. The comparison is case-insensitive on both columns,
    matching the parsers' own case-insensitive card_type dispatch rather than
    create_card()'s case-sensitive UNIQUE constraint (the known asymmetry in
    STATE.md's open flags): a card created by hand as "diners" should still
    be found when the PDF is detected as "Diners".

    `last_statement_period` is {"period_start", "period_end"} of the
    statement with the latest period_end, or None for a card with no
    statements yet (two correlated scalar subqueries, same ordering, so the
    pair always comes from one statement row). Ordered by card id so the
    candidate list is stable.
    """
    rows = conn.execute(
        """
        SELECT cards.id, cards.bank, cards.card_type, cards.nickname,
               (SELECT period_start FROM statements WHERE card_id = cards.id
                ORDER BY period_end DESC, period_start DESC LIMIT 1) AS period_start,
               (SELECT period_end FROM statements WHERE card_id = cards.id
                ORDER BY period_end DESC, period_start DESC LIMIT 1) AS period_end
        FROM cards
        WHERE cards.bank = ? COLLATE NOCASE AND cards.card_type = ? COLLATE NOCASE
        ORDER BY cards.id ASC
        """,
        (bank, card_type),
    ).fetchall()
    out = []
    for row in rows:
        period = None
        if row["period_end"] is not None:
            period = {"period_start": row["period_start"], "period_end": row["period_end"]}
        out.append(
            {
                "card_id": row["id"],
                "bank": row["bank"],
                "card_type": row["card_type"],
                "nickname": row["nickname"],
                "last_statement_period": period,
            }
        )
    return out


def list_cards(conn: sqlite3.Connection) -> "list[dict]":
    rows = conn.execute("SELECT * FROM cards ORDER BY created_at").fetchall()
    return [dict(row) for row in rows]


def list_cards_with_statements(
    conn: sqlite3.Connection,
    statement_month: "str | None" = None,
    bank: "str | None" = None,
    card_type: "str | None" = None,
    start_date=None,
    end_date=None,
    category: "str | None" = None,
    subcategory: "str | None" = None,
    merchant: "str | None" = None,
) -> "list[dict]":
    """Cards that have at least one statement, ordered by id ascending,
    optionally narrowed by statement month, bank, card type, or a date range.

    Explicit `cards.*` (not a bare `*`) for the same reason as the
    transactions/statements read-path JOIN: both `cards` and `statements`
    have an `id` column, so a bare `*` would collide. `DISTINCT` collapses
    the JOIN's one-row-per-statement (or per-transaction, with a date range)
    fan-out back down to one row per card.

    The filters are the shared read-path set from storage.reads.filter_sql,
    anchored on cards with the statements JOIN always on (that is what
    "with statements" means). There is no card_id parameter: a filter is
    never narrowed by itself.
    """
    from storage.reads import filter_sql  # local import: reads is the lower layer

    joins, where, params = filter_sql(
        "cards",
        statement_month=statement_month,
        bank=bank,
        card_type=card_type,
        start_date=start_date,
        end_date=end_date,
        category=category,
        subcategory=subcategory,
        merchant=merchant,
        always_join=("statements",),
    )
    rows = conn.execute(
        "SELECT DISTINCT cards.* FROM cards" + joins + where + " ORDER BY cards.id ASC",
        params,
    ).fetchall()
    return [dict(row) for row in rows]
