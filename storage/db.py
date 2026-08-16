import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv

from storage.schema import CREATE_STATEMENTS_TABLE, CREATE_TRANSACTIONS_TABLE

load_dotenv()

DEFAULT_DB_PATH = "data/tracker.db"


def _get_db_path() -> str:
    return os.environ.get("DB_PATH", DEFAULT_DB_PATH)


def get_connection() -> sqlite3.Connection:
    db_path = _get_db_path()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_connection()
    try:
        conn.execute(CREATE_STATEMENTS_TABLE)
        conn.execute(CREATE_TRANSACTIONS_TABLE)
        conn.commit()
    finally:
        conn.close()
