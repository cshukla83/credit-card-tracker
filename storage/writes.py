import sqlite3
from datetime import date


def _to_date_str(value):
    return value.isoformat() if isinstance(value, date) else value


def insert_statement(
    conn: sqlite3.Connection,
    bank: str,
    period_start: date,
    period_end: date,
    transactions: "list[dict]",
) -> "int | None":
    """Insert a statement and its transactions as one atomic write.

    Returns the new statement's id, or None if a statement for this
    (bank, period_start, period_end) was already imported (in which case
    nothing is written — this call is a no-op dedup skip).

    If any transaction fails to insert (e.g. a NOT NULL violation), the
    whole write — including the statement row — rolls back, so a statement
    row never ends up with a partial or missing set of transactions.
    """
    try:
        with conn:
            cursor = conn.execute(
                "INSERT INTO statements (bank, period_start, period_end) VALUES (?, ?, ?)",
                (bank, _to_date_str(period_start), _to_date_str(period_end)),
            )
            statement_id = cursor.lastrowid

            for txn in transactions:
                conn.execute(
                    "INSERT INTO transactions "
                    "(statement_id, txn_date, description, amount, txn_type, reward_points) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        statement_id,
                        _to_date_str(txn["txn_date"]),
                        txn["description"],
                        txn["amount"],
                        txn["txn_type"],
                        txn.get("reward_points"),
                    ),
                )
    except sqlite3.IntegrityError:
        return None

    return statement_id
