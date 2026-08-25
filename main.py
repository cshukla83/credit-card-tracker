from datetime import date

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse

from storage.cards import list_cards_with_statements
from storage.db import get_connection, init_db
from storage.reads import get_transactions, list_card_types, list_statement_months

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
    statement_month: str | None = None,
    bank: str | None = None,
    card_type: str | None = None,
    conn=Depends(get_db),
):
    start_date = _parse_query_date(start, "start") if start is not None else None
    end_date = _parse_query_date(end, "end") if end is not None else None

    if start_date is not None and end_date is not None and start_date > end_date:
        raise HTTPException(
            status_code=400,
            detail=f"start ({start_date}) is after end ({end_date})",
        )

    # Always 200 + [] when nothing matches -- including an unknown card_id,
    # statement_month, bank, or card_type. Same reasoning throughout: the
    # storage layer doesn't distinguish "no such value" from "value exists
    # but has no matching transactions," so this endpoint doesn't either --
    # no format validation, no 400s, for these three, unlike start/end.
    return get_transactions(
        conn,
        card_id=card_id,
        start_date=start_date,
        end_date=end_date,
        statement_month=statement_month,
        bank=bank,
        card_type=card_type,
    )


@app.get("/cards")
def read_cards(conn=Depends(get_db)):
    return list_cards_with_statements(conn)


@app.get("/statement-months")
def read_statement_months(conn=Depends(get_db)):
    return list_statement_months(conn)


@app.get("/card-types")
def read_card_types(conn=Depends(get_db)):
    return list_card_types(conn)
