from datetime import date

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator, model_validator

from storage.cards import list_cards_with_statements
from storage.categories import (
    TransactionNotFoundError,
    assign_categories,
    cluster_transactions,
    list_categories,
    list_subcategories,
    suggest_categories,
    suggest_category,
)
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


def _parse_date_range(start: "str | None", end: "str | None"):
    # Shared by every filterable read endpoint: malformed -> 400 naming the
    # param; start after end -> 400. Both are the only inputs here that have
    # a format to get wrong, which is why they get 400s while the other
    # filters get "200 + empty" (see read_transactions).
    start_date = _parse_query_date(start, "start") if start is not None else None
    end_date = _parse_query_date(end, "end") if end is not None else None
    if start_date is not None and end_date is not None and start_date > end_date:
        raise HTTPException(
            status_code=400,
            detail=f"start ({start_date}) is after end ({end_date})",
        )
    return start_date, end_date


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
    start_date, end_date = _parse_date_range(start, end)

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


# The three listing endpoints accept the same filters as /transactions,
# minus the one each of them *is* -- so a frontend can ask "which cards have
# data in this month/range" or "which months exist for this card" and
# narrow every picker by the others without a picker ever narrowing itself.
@app.get("/cards")
def read_cards(
    statement_month: str | None = None,
    bank: str | None = None,
    card_type: str | None = None,
    start: str | None = None,
    end: str | None = None,
    conn=Depends(get_db),
):
    start_date, end_date = _parse_date_range(start, end)
    return list_cards_with_statements(
        conn,
        statement_month=statement_month,
        bank=bank,
        card_type=card_type,
        start_date=start_date,
        end_date=end_date,
    )


@app.get("/statement-months")
def read_statement_months(
    card_id: int | None = None,
    bank: str | None = None,
    card_type: str | None = None,
    start: str | None = None,
    end: str | None = None,
    conn=Depends(get_db),
):
    start_date, end_date = _parse_date_range(start, end)
    return list_statement_months(
        conn,
        card_id=card_id,
        bank=bank,
        card_type=card_type,
        start_date=start_date,
        end_date=end_date,
    )


@app.get("/card-types")
def read_card_types(
    card_id: int | None = None,
    statement_month: str | None = None,
    bank: str | None = None,
    start: str | None = None,
    end: str | None = None,
    conn=Depends(get_db),
):
    start_date, end_date = _parse_date_range(start, end)
    return list_card_types(
        conn,
        card_id=card_id,
        statement_month=statement_month,
        bank=bank,
        start_date=start_date,
        end_date=end_date,
    )


@app.get("/categories")
def read_categories(conn=Depends(get_db)):
    # The catalog of categories in use -- there is no predefined list, so
    # this is what the frontend's dropdown/typeahead is populated from.
    return list_categories(conn)


@app.get("/subcategories")
def read_subcategories(category: str | None = None, conn=Depends(get_db)):
    # Sorted distinct subcategories in use; ?category= narrows to rows with
    # that category. Feeds the per-row subcategory dropdown.
    return list_subcategories(conn, category=category)


@app.get("/transactions/{transaction_id}/suggestion")
def read_category_suggestion(transaction_id: int, conn=Depends(get_db)):
    # Returns {"category": {value, confidence, match_type},
    #          "subcategory": {value, confidence, match_type} | null}
    # (Session 53 shape; the flat single-suggestion shape is gone).
    # Unlike the /transactions filters, an unknown id here is a real 404:
    # there is no "exists but has nothing to suggest" ambiguity -- that case
    # is a 200 with match_type "none".
    try:
        return suggest_category(conn, transaction_id)
    except TransactionNotFoundError:
        raise HTTPException(status_code=404, detail=f"No such transaction: {transaction_id}")


class SuggestionBatch(BaseModel):
    transaction_ids: list[int] = Field(min_length=1)


@app.post("/transactions/suggestions")
def read_category_suggestions(body: SuggestionBatch, conn=Depends(get_db)):
    # Batch counterpart of the single-id GET: the categorized-transaction
    # query runs once for the whole list rather than once per id. Any
    # unknown id is a 404 for the whole request, nothing computed.
    try:
        return {"suggestions": suggest_categories(conn, body.transaction_ids)}
    except TransactionNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"No such transaction(s): {e.missing_ids}")


class ClusterRequest(BaseModel):
    transaction_ids: list[int]
    # Percentage of the 0-1 similarity ratio; 70 admits pairs at >= 0.70.
    threshold: int = Field(default=70, ge=0, le=100)


@app.post("/transactions/clusters")
def read_clusters(body: ClusterRequest, conn=Depends(get_db)):
    # Groups the given transactions by description similarity, anchor-based,
    # in the order given. Returns only clusters of two or more -- there is
    # deliberately no "ungrouped" list; a transaction that matched nothing
    # is simply absent. Empty input and all-singletons both return an
    # empty list, not an error. Unknown ids are a 404 like everywhere else.
    try:
        return {"clusters": cluster_transactions(conn, body.transaction_ids, body.threshold)}
    except TransactionNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"No such transaction(s): {e.missing_ids}")


def normalize_category(value: str) -> str:
    """The one place a category or subcategory value is shaped before storage.

    strip() then str.title(). NULL is the only representation of
    "uncategorized", so an empty or whitespace-only category is rejected
    rather than stored. Stripping keeps " Food" and "Food" from becoming
    two catalog entries; title-casing keeps "food" and "Food" from doing
    the same, whatever client sent them.

    str.title() is a deliberately simple rule, not a smart title-caser:
    it capitalises after any non-letter, so "mcdonald's" becomes
    "Mcdonald'S" and "e-commerce" becomes "E-Commerce". Known and accepted
    (Session 49) -- no special-casing until a real example causes a real
    problem. Applied server-side so the stored form is consistent
    regardless of what called the API; the Session 49 backfill applied the
    same function to rows written before it existed. Subcategory (Session
    53) uses this same function -- one rule, not a copy.
    """
    value = value.strip().title()
    if not value:
        raise ValueError("category must not be empty")
    return value


class CategoryAssignment(BaseModel):
    transaction_id: int
    category: str | None = None
    subcategory: str | None = None

    @field_validator("category", "subcategory")
    @classmethod
    def _normalize(cls, value: "str | None") -> "str | None":
        # None means "leave this column alone"; a present value gets the
        # shared normalization and must survive it non-empty.
        return None if value is None else normalize_category(value)

    @model_validator(mode="after")
    def _require_a_field(self):
        if self.category is None and self.subcategory is None:
            raise ValueError("each assignment needs category or subcategory (or both)")
        return self


class CategoryAssignmentBatch(BaseModel):
    assignments: list[CategoryAssignment] = Field(min_length=1)


@app.post("/transactions/category")
def write_category(body: CategoryAssignmentBatch, conn=Depends(get_db)):
    # A list of (transaction_id, category) pairs so one call can write
    # different categories to different rows -- "accept suggestions" on a
    # selection spanning several suggestion groups needs that. A uniform
    # assignment is just N pairs with the same category; a single id is a
    # list of length 1. This is a direct write -- it never consults the
    # suggestion engine.
    # Each entry writes only the field(s) it carries; the other column on
    # that row is left as it is (Session 53).
    pairs = [(a.transaction_id, a.category, a.subcategory) for a in body.assignments]
    try:
        updated = assign_categories(conn, pairs)
    except TransactionNotFoundError as e:
        # All-or-nothing: if any id is unknown nothing was written, so the
        # whole request is a 404 naming the ids that were missing.
        raise HTTPException(status_code=404, detail=f"No such transaction(s): {e.missing_ids}")
    except ValueError as e:
        # The same id with two different values for one field in one request.
        raise HTTPException(status_code=422, detail=str(e))
    return {"updated": updated}
