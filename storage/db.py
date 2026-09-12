import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv

from storage.schema import (
    ADD_CATEGORY_COLUMN,
    ADD_IS_PAYMENT_COLUMN,
    ADD_MERCHANT_COLUMN,
    ADD_SUBCATEGORY_COLUMN,
    ADD_STATEMENT_MONTH_COLUMN,
    CREATE_CARDS_TABLE,
    CREATE_STATEMENTS_TABLE,
    CREATE_TRANSACTIONS_TABLE,
)

load_dotenv()

DEFAULT_DB_PATH = "data/tracker.db"


def _get_db_path() -> str:
    return os.environ.get("DB_PATH", DEFAULT_DB_PATH)


def get_connection() -> sqlite3.Connection:
    db_path = _get_db_path()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    # FastAPI's Depends(get_db) runs dependency setup, the endpoint
    # handler, and generator teardown across different threadpool
    # threads. sqlite3 defaults to check_same_thread=True which
    # crashes on cross-thread connection use -- including during
    # teardown for endpoints that appear to work otherwise. This
    # flag protects against *concurrent* use from multiple threads;
    # every caller here uses each connection sequentially from at
    # most one thread at a time (CLIs are single-threaded; the
    # FastAPI dependency creates a fresh connection per request),
    # so disabling it is safe. Discovered Session 26, latent since
    # Session 23.
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_connection()
    try:
        conn.execute(CREATE_CARDS_TABLE)
        conn.execute(CREATE_STATEMENTS_TABLE)
        conn.execute(CREATE_TRANSACTIONS_TABLE)
        _ensure_statement_month_column(conn)
        _ensure_category_column(conn)
        _ensure_subcategory_column(conn)
        _ensure_merchant_column(conn)
        _ensure_is_payment_column(conn)
        conn.commit()
    finally:
        conn.close()


def _ensure_statement_month_column(conn: sqlite3.Connection) -> None:
    # CREATE TABLE IF NOT EXISTS above is a no-op against a DB created before
    # this column existed, so a DB from an earlier session needs this
    # explicit ALTER TABLE migration. Empirically, PRAGMA table_info omits
    # generated columns entirely (verified: it listed only 5 of 6 columns on
    # a table whose CREATE TABLE already included statement_month), so it
    # can never see the column and would re-run the ALTER on every call,
    # failing with "duplicate column name" the moment the column already
    # exists -- including on a table that was just freshly created with it.
    # PRAGMA table_xinfo does include generated columns (with a nonzero
    # `hidden` value) and is used here instead; that's the real idempotency
    # check.
    columns = {row["name"] for row in conn.execute("PRAGMA table_xinfo(statements)")}
    if "statement_month" not in columns:
        conn.execute(ADD_STATEMENT_MONTH_COLUMN)


def _ensure_category_column(conn: sqlite3.Connection) -> None:
    # Same idiom as _ensure_statement_month_column: CREATE TABLE IF NOT EXISTS
    # never touches a pre-existing table, so a DB from before this column
    # needs an explicit ALTER. table_xinfo is used for consistency with the
    # check above (table_info would also work here -- category is a plain
    # column, not a generated one -- but one idiom for both keeps them
    # comparable).
    columns = {row["name"] for row in conn.execute("PRAGMA table_xinfo(transactions)")}
    if "category" not in columns:
        conn.execute(ADD_CATEGORY_COLUMN)


def _ensure_subcategory_column(conn: sqlite3.Connection) -> None:
    # Third copy of the same idiom (Session 53): table_xinfo check, ALTER only
    # if absent, so init_db() stays idempotent on fresh and migrated DBs.
    columns = {row["name"] for row in conn.execute("PRAGMA table_xinfo(transactions)")}
    if "subcategory" not in columns:
        conn.execute(ADD_SUBCATEGORY_COLUMN)


def _ensure_merchant_column(conn: sqlite3.Connection) -> None:
    # Fourth copy of the idiom (Session 55): table_xinfo check, ALTER only if
    # absent.
    columns = {row["name"] for row in conn.execute("PRAGMA table_xinfo(transactions)")}
    if "merchant" not in columns:
        conn.execute(ADD_MERCHANT_COLUMN)


def _ensure_is_payment_column(conn: sqlite3.Connection) -> None:
    # Fifth copy of the idiom (Session 61).
    columns = {row["name"] for row in conn.execute("PRAGMA table_xinfo(transactions)")}
    if "is_payment" not in columns:
        conn.execute(ADD_IS_PAYMENT_COLUMN)
