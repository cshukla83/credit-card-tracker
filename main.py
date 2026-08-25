from datetime import date

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse

from storage.cards import list_cards_with_statements
from storage.db import get_connection, init_db
from storage.reads import get_transactions

app = FastAPI()


@app.get("/")
def read_root():
    return FileResponse("static/index.html")


def get_db():
    # init_db() runs here, per request, rather than once at module import
    # time -- it's idempotent (CREATE TABLE IF NOT EXISTS), so calling it
    # every time costs nothing, but it means DB_PATH is always read fresh
    # (the Session 16 invariant), letting tests point the DB at a temp path
    # via monkeypatch.setenv without needing main.py to be re-imported.
    init_db()
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def _parse_query_date(value: str, param_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {param_name} date: {value!r} (expected YYYY-MM-DD)",
        )


@app.get("/transactions")
def read_transactions(
    card_id: int | None = None,
    start: str | None = None,
    end: str | None = None,
    conn=Depends(get_db),
):
    start_date = _parse_query_date(start, "start") if start is not None else None
    end_date = _parse_query_date(end, "end") if end is not None else None

    if start_date is not None and end_date is not None and start_date > end_date:
        raise HTTPException(
            status_code=400,
            detail=f"start ({start_date}) is after end ({end_date})",
        )

    # Always 200 + [] when nothing matches -- including an unknown card_id.
    # get_transactions() (and the storage layer generally) doesn't
    # distinguish "no such card" from "card exists but has no matching
    # transactions" for the given range, so this endpoint doesn't either: a
    # second lookup just to draw that distinction isn't worth it when the
    # response is an empty list either way.
    return get_transactions(conn, card_id=card_id, start_date=start_date, end_date=end_date)


@app.get("/cards")
def read_cards(conn=Depends(get_db)):
    return list_cards_with_statements(conn)
