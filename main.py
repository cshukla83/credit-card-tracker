from datetime import date

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator, model_validator

from storage.aggregate import DimensionsError, PeriodError, aggregate_spend, resolve_period
from storage.cards import list_cards_with_statements
from storage.commentary import (
    CommentaryNotConfiguredError,
    CommentaryUnavailableError,
    generate_commentary,
    query_signature,
)
from storage.categories import (
    InvalidPaymentFlagError,
    TransactionNotFoundError,
    assign_categories,
    cluster_transactions,
    list_categories,
    list_merchants,
    list_subcategories,
    suggest_categories,
    suggest_category,
)
from storage.db import get_connection, init_db
from storage.reads import (
    ReviewStatusError,
    get_transactions,
    list_card_types,
    list_statement_months,
)

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
    category: str | None = None,
    subcategory: str | None = None,
    merchant: str | None = None,
    review_status: str | None = None,
    conn=Depends(get_db),
):
    start_date, end_date = _parse_date_range(start, end)

    # Always 200 + [] when nothing matches -- including an unknown card_id,
    # statement_month, bank, or card_type. Same reasoning throughout: the
    # storage layer doesn't distinguish "no such value" from "value exists
    # but has no matching transactions," so this endpoint doesn't either --
    # no format validation, no 400s, for these three, unlike start/end.
    # review_status (Session 80) is the one filter with a closed value set,
    # so it alone can be invalid: 422, like a bad `dimensions`.
    try:
        return get_transactions(
            conn,
            card_id=card_id,
            start_date=start_date,
            end_date=end_date,
            statement_month=statement_month,
            bank=bank,
            card_type=card_type,
            category=category,
            subcategory=subcategory,
            merchant=merchant,
            review_status=review_status,
        )
    except ReviewStatusError as e:
        raise HTTPException(status_code=422, detail=str(e))


# The three listing endpoints accept the same filters as /transactions,
# minus the one each of them *is* -- so a frontend can ask "which cards have
# data in this month/range" or "which months exist for this card" and
# narrow every picker by the others without a picker ever narrowing itself.
@app.get("/transactions/aggregate")
def read_aggregate(
    granularity: str | None = None,
    mode: str | None = None,
    count: int | None = None,
    month: str | None = None,
    quarter: str | None = None,
    year: str | None = None,
    start: str | None = None,
    end: str | None = None,
    bank: str | None = None,
    card_id: int | None = None,
    card_type: str | None = None,
    category: str | None = None,
    subcategory: str | None = None,
    merchant: str | None = None,
    review_status: str | None = None,
    dimensions: str | None = None,
    conn=Depends(get_db),
):
    # Spend over a period as a nested tree (Session 65; arbitrary-order
    # 2- or 3-level `dimensions`, comma-separated, and combinable label
    # filters since Session 74; default `category,subcategory` is the
    # original shape). The
    # period is resolved server-side and echoed back as concrete dates, so a
    # client never re-derives them. Invalid period specs are 422 with the
    # reason; filters are the shared read-path set and, as on /transactions,
    # an unknown bank / card is an empty result, not an error.
    try:
        start_date, end_date = resolve_period(
            granularity, mode=mode, count=count, month=month, quarter=quarter,
            year=year, start=start, end=end,
        )
    except PeriodError as e:
        raise HTTPException(status_code=422, detail=str(e))
    dims = [d.strip() for d in dimensions.split(",")] if dimensions is not None else None
    try:
        return aggregate_spend(
            conn, start_date, end_date, bank=bank, card_id=card_id, card_type=card_type,
            dimensions=dims, category=category, subcategory=subcategory, merchant=merchant,
            review_status=review_status,
        )
    except (DimensionsError, ReviewStatusError) as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.post("/analytics/commentary")
def write_commentary(
    granularity: str | None = None,
    mode: str | None = None,
    count: int | None = None,
    month: str | None = None,
    quarter: str | None = None,
    year: str | None = None,
    start: str | None = None,
    end: str | None = None,
    bank: str | None = None,
    card_id: int | None = None,
    card_type: str | None = None,
    conn=Depends(get_db),
):
    # LLM commentary for the dashboard (Session 68). Same period and filter
    # params as /transactions/aggregate; a plain action, invoked on explicit
    # user request, never polled. Period resolved once, aggregate computed
    # once, and only the narrowed category-level payload leaves the machine.
    # Missing key -> 500 (configuration, not transient); model failure with
    # a cached row -> that row, cached: true; without one -> 503.
    try:
        start_date, end_date = resolve_period(
            granularity, mode=mode, count=count, month=month, quarter=quarter,
            year=year, start=start, end=end,
        )
    except PeriodError as e:
        raise HTTPException(status_code=422, detail=str(e))
    # Full three-level tree (Session 73/74): the narrowed payload carries
    # labels down to merchant, amounts only.
    aggregate = aggregate_spend(
        conn, start_date, end_date, bank=bank, card_id=card_id, card_type=card_type,
        dimensions=["category", "subcategory", "merchant"],
    )
    signature = query_signature(start_date, end_date, bank=bank, card_id=card_id, card_type=card_type)
    try:
        return generate_commentary(conn, aggregate, signature)
    except CommentaryNotConfiguredError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except CommentaryUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/cards")
def read_cards(
    statement_month: str | None = None,
    bank: str | None = None,
    card_type: str | None = None,
    start: str | None = None,
    end: str | None = None,
    category: str | None = None,
    subcategory: str | None = None,
    merchant: str | None = None,
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
        category=category,
        subcategory=subcategory,
        merchant=merchant,
    )


@app.get("/statement-months")
def read_statement_months(
    card_id: int | None = None,
    bank: str | None = None,
    card_type: str | None = None,
    start: str | None = None,
    end: str | None = None,
    category: str | None = None,
    subcategory: str | None = None,
    merchant: str | None = None,
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
        category=category,
        subcategory=subcategory,
        merchant=merchant,
    )


@app.get("/card-types")
def read_card_types(
    card_id: int | None = None,
    statement_month: str | None = None,
    bank: str | None = None,
    start: str | None = None,
    end: str | None = None,
    category: str | None = None,
    subcategory: str | None = None,
    merchant: str | None = None,
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
        category=category,
        subcategory=subcategory,
        merchant=merchant,
    )


# The three label catalogs join the filter-bar mesh (Session 75): each is
# narrowed by bank / card / card type / statement month / date range, and
# each narrows those in return (see /cards etc. above) -- but none of the
# three narrows another. They are independent peers in the filter bar, not
# a cascade like Bank -> Card, mirroring the chart's own design where the
# three are selected independently.
def _mesh(bank, card_id, card_type, statement_month, start, end):
    start_date, end_date = _parse_date_range(start, end)
    return dict(
        bank=bank, card_id=card_id, card_type=card_type,
        statement_month=statement_month, start_date=start_date, end_date=end_date,
    )


@app.get("/categories")
def read_categories(
    bank: str | None = None,
    card_id: int | None = None,
    card_type: str | None = None,
    statement_month: str | None = None,
    start: str | None = None,
    end: str | None = None,
    conn=Depends(get_db),
):
    # The catalog of categories in use -- there is no predefined list, so
    # this is what the frontend's dropdown/typeahead is populated from.
    return list_categories(conn, **_mesh(bank, card_id, card_type, statement_month, start, end))


@app.get("/merchants")
def read_merchants(
    bank: str | None = None,
    card_id: int | None = None,
    card_type: str | None = None,
    statement_month: str | None = None,
    start: str | None = None,
    end: str | None = None,
    conn=Depends(get_db),
):
    # Sorted distinct merchants in use; never scoped by category or
    # subcategory. Feeds the merchant dropdown and the multi-select typeahead.
    return list_merchants(conn, **_mesh(bank, card_id, card_type, statement_month, start, end))


@app.get("/subcategories")
def read_subcategories(
    category: str | None = None,
    bank: str | None = None,
    card_id: int | None = None,
    card_type: str | None = None,
    statement_month: str | None = None,
    start: str | None = None,
    end: str | None = None,
    conn=Depends(get_db),
):
    # Sorted distinct subcategories in use; ?category= is the review
    # screen's per-row scoping (pre-Session-75, unchanged); the rest is the
    # filter-bar mesh.
    return list_subcategories(
        conn, category=category, **_mesh(bank, card_id, card_type, statement_month, start, end)
    )


@app.get("/transactions/{transaction_id}/suggestion")
def read_category_suggestion(transaction_id: int, conn=Depends(get_db)):
    # Returns {"category": {value, confidence, match_type},
    #          "subcategory": {value, confidence, match_type} | null,
    #          "merchant": {value, confidence, match_type}}
    # (Session 55 shape; merchant is never null -- its Tier 3 fallback
    # always yields a value, with confidence null for "from_description").
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


# The one place a category, subcategory, or merchant value is shaped before
# storage -- strip() then Title Case, reject empty. NULL is the only
# representation of "unset", so an empty or whitespace-only value is rejected
# rather than stored; stripping keeps " Food" and "Food" from becoming two
# catalog entries, title-casing keeps "food" and "Food" from doing the same.
# Since Session 74 the rule itself lives in storage.normalize so the read-path
# filters can apply the identical normalisation; this name is kept for the
# validator and any caller that imports it from here.
from storage.normalize import normalize_label as normalize_category  # noqa: E402


class CategoryAssignment(BaseModel):
    transaction_id: int
    category: str | None = None
    subcategory: str | None = None
    merchant: str | None = None
    # Boolean flag with a cascade (Session 61): True also writes the three
    # labels to their payment values; False reverts them to NULL. Resolved
    # against the row's current state in storage; same value = no-op.
    is_payment: bool | None = None

    @field_validator("category", "subcategory", "merchant")
    @classmethod
    def _normalize(cls, value: "str | None") -> "str | None":
        # None means "leave this column alone"; a present value gets the
        # shared normalization and must survive it non-empty.
        return None if value is None else normalize_category(value)

    @model_validator(mode="after")
    def _require_a_field(self):
        if (
            self.category is None
            and self.subcategory is None
            and self.merchant is None
            and self.is_payment is None
        ):
            raise ValueError(
                "each assignment needs at least one of category, subcategory, merchant, is_payment"
            )
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
    pairs = [
        (a.transaction_id, a.category, a.subcategory, a.merchant, a.is_payment)
        for a in body.assignments
    ]
    try:
        updated = assign_categories(conn, pairs)
    except TransactionNotFoundError as e:
        # All-or-nothing: if any id is unknown nothing was written, so the
        # whole request is a 404 naming the ids that were missing.
        raise HTTPException(status_code=404, detail=f"No such transaction(s): {e.missing_ids}")
    except InvalidPaymentFlagError as e:
        # Semantically invalid, not malformed: a debit can never be a payment
        # to the card. 400, nothing written.
        raise HTTPException(
            status_code=400,
            detail=f"is_payment can only be set on credit transactions: {e.invalid_ids}",
        )
    except ValueError as e:
        # The same id with two different values for one field in one request.
        raise HTTPException(status_code=422, detail=str(e))
    return {"updated": updated}
