import sqlite3


class CardAlreadyExistsError(Exception):
    """Raised when create_card() collides with the (bank, card_type, nickname) UNIQUE constraint.

    Card creation is an explicit user action, so a collision here is treated
    as a user-facing error rather than a silent skip (unlike insert_statement(),
    where a dedup collision during bulk import is the expected, correct outcome).
    """


def create_card(
    conn: sqlite3.Connection, bank: str, card_type: str, nickname: "str | None" = None
) -> int:
    try:
        with conn:
            cursor = conn.execute(
                "INSERT INTO cards (bank, card_type, nickname) VALUES (?, ?, ?)",
                (bank, card_type, nickname),
            )
    except sqlite3.IntegrityError as e:
        raise CardAlreadyExistsError(
            f"Card already exists: bank={bank!r}, card_type={card_type!r}, nickname={nickname!r}"
        ) from e

    return cursor.lastrowid


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


def list_cards(conn: sqlite3.Connection) -> "list[dict]":
    rows = conn.execute("SELECT * FROM cards ORDER BY created_at").fetchall()
    return [dict(row) for row in rows]
