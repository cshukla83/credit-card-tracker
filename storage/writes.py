import sqlite3
from datetime import date

from storage.cards import insert_card_row
from storage.dates import to_date_str


def _insert_statement_rows(
    conn: sqlite3.Connection,
    card_id: int,
    period_start: date,
    period_end: date,
    transactions: "list[dict]",
) -> int:
    """The statement and transaction INSERTs alone, inside the caller's
    transaction. Session 112 split this out of insert_statement() so the
    same rows can be written after a new card in one atomic unit."""
    cursor = conn.execute(
        "INSERT INTO statements (card_id, period_start, period_end) VALUES (?, ?, ?)",
        (card_id, to_date_str(period_start), to_date_str(period_end)),
    )
    statement_id = cursor.lastrowid

    for txn in transactions:
        conn.execute(
            "INSERT INTO transactions "
            "(statement_id, txn_date, description, amount, txn_type, reward_points, "
            "is_payment) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                statement_id,
                to_date_str(txn["txn_date"]),
                txn["description"],
                txn["amount"],
                txn["txn_type"],
                txn.get("reward_points"),
                # Boolean, never NULL: absent (older callers, tests
                # building rows by hand) means "not a payment".
                1 if txn.get("is_payment") else 0,
            ),
        )
    return statement_id


def insert_statement(
    conn: sqlite3.Connection,
    card_id: int,
    period_start: date,
    period_end: date,
    transactions: "list[dict]",
) -> "int | None":
    """Insert a statement and its transactions as one atomic write.

    Returns the new statement's id, or None if a statement for this
    (card_id, period_start, period_end) was already imported (in which case
    nothing is written — this call is a no-op dedup skip).

    If any transaction fails to insert (e.g. a NOT NULL violation), the
    whole write — including the statement row — rolls back, so a statement
    row never ends up with a partial or missing set of transactions.

    A non-existent card_id fires the FOREIGN KEY constraint rather than the
    UNIQUE constraint used for dedup, and is re-raised rather than swallowed:
    it means the caller passed a bad id, not that this statement was already
    imported. Every other IntegrityError (the UNIQUE dedup case, or a
    malformed transaction row violating e.g. NOT NULL) still returns None,
    matching Session 17's original atomicity behavior.
    """
    try:
        with conn:
            return _insert_statement_rows(conn, card_id, period_start, period_end, transactions)
    except sqlite3.IntegrityError as e:
        # Python's sqlite3 module raises the same IntegrityError class for
        # UNIQUE and FOREIGN KEY violations -- there's no distinct exception
        # type to catch separately. e.sqlite_errorname exposes the underlying
        # SQLite error code (verified empirically in Session 18) as the only
        # way to tell them apart here.
        if e.sqlite_errorname == "SQLITE_CONSTRAINT_FOREIGNKEY":
            raise
        return None


def insert_statement_with_new_card(
    conn: sqlite3.Connection,
    bank: str,
    card_type: str,
    nickname: "str | None",
    period_start: date,
    period_end: date,
    transactions: "list[dict]",
) -> "tuple[int, int]":
    """Create a card and its first statement as ONE atomic write (Session 112).

    Returns (card_id, statement_id). The card row and the statement's rows
    are inserted inside a single transaction: a nickname collision raises
    CardAlreadyExistsError with nothing written; any failure while writing
    the statement or its transactions rolls the card back too. A card
    created here therefore exists only if its statement does -- the upload
    flow's fix for orphan cards left behind by a preview that was never
    confirmed. No dedup skip: a card that did not exist a moment ago cannot
    already hold this statement, so an IntegrityError on the rows is a
    malformed row and is raised, not swallowed.
    """
    with conn:
        card_id = insert_card_row(conn, bank, card_type, nickname)
        statement_id = _insert_statement_rows(conn, card_id, period_start, period_end, transactions)
    return card_id, statement_id
