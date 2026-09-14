import sqlite3
from collections import Counter
from difflib import SequenceMatcher


class TransactionNotFoundError(Exception):
    """Raised when a transaction id (or ids) passed by a caller does not exist.

    Carries the missing ids so an API layer can report exactly which ones
    were bad rather than just "not found".
    """

    def __init__(self, missing_ids: "list[int]"):
        self.missing_ids = missing_ids
        super().__init__(f"No such transaction(s): {missing_ids}")


def fuzzy_similarity(a: str, b: str) -> float:
    """The codebase's one definition of "how similar are these two descriptions".

    difflib.SequenceMatcher(None, a, b).ratio() over both strings casefolded,
    so a case difference never depresses the score (Session 41's Tier 2
    decision, now shared). 0.0 = nothing in common, 1.0 = identical after
    casefolding. Argument order follows SequenceMatcher's: the first string
    is the one being matched *from*, the second the candidate. Used by the
    suggestion engine's Tier 2 and by cluster_by_similarity().
    """
    return SequenceMatcher(None, a.casefold(), b.casefold()).ratio()


def _no_suggestion() -> dict:
    return {"value": None, "confidence": 0.0, "match_type": "none"}


def _fetch_labeled(conn: sqlite3.Connection) -> "list[sqlite3.Row]":
    """Every transaction carrying a category or a merchant, id-descending.

    This is the one query behind both suggestion entry points and all three
    suggestion engines. The batch path runs it once and reuses the rows for
    every id in the request; each engine filters the rows it can learn from
    (category/subcategory: `category IS NOT NULL`; merchant: `merchant IS
    NOT NULL`) in Python, and excludes the target itself there too, so the
    same row set serves many targets. (Named `_fetch_categorized` until
    Session 55 widened it to merchant-bearing rows.)

    Comparisons happen in Python rather than SQL because SQLite's
    LOWER()/NOCASE are ASCII-only while str.casefold() is Unicode-aware,
    and the fuzzy tier has to happen in Python anyway -- so one code path
    with one definition of "case-insensitive".
    """
    return conn.execute(
        "SELECT id, description, category, subcategory, merchant FROM transactions "
        "WHERE category IS NOT NULL OR merchant IS NOT NULL ORDER BY id DESC"
    ).fetchall()


def _fetch_targets(conn: sqlite3.Connection, transaction_ids: "list[int]") -> "dict[int, sqlite3.Row]":
    """id -> row (id, description, category, merchant) for the given ids; raises if any is unknown.

    merchant (Session 88) feeds the subcategory engine's precedent tier."""
    placeholders = ",".join("?" * len(transaction_ids))
    rows = conn.execute(
        f"SELECT id, description, category, merchant FROM transactions WHERE id IN ({placeholders})",
        transaction_ids,
    ).fetchall()
    found = {row["id"]: row for row in rows}
    missing = [i for i in transaction_ids if i not in found]
    if missing:
        raise TransactionNotFoundError(missing)
    return found


def _exact_tier(needle: str, candidates: "list[sqlite3.Row]", field: str) -> "dict | None":
    """Tier 1: case-insensitive description equality; majority vote on `field`.

    No other normalization (whitespace, digits, punctuation are compared
    as-is); a decision, not an oversight -- see DEVLOG Session 41. If the
    matches span several values, the most frequent wins; confidence is that
    value's share of the exact matches (1.0 when they all agree), so a 50/50
    split reports 0.5 rather than a misleading 1.0.

    Candidates arrive id-descending, so the first hit per value is that
    value's most recent one; Counter.most_common() preserves first-seen
    order among equal counts, which makes the highest-id tie-break fall out
    of the ordering rather than needing a second sort key.
    """
    exact = [row for row in candidates if row["description"].casefold() == needle]
    if not exact:
        return None
    counts = Counter(row[field] for row in exact)
    value, count = counts.most_common(1)[0]
    return {"value": value, "confidence": count / len(exact), "match_type": "exact"}


def _fuzzy_tier(needle: str, candidates: "list[sqlite3.Row]", field: str) -> dict:
    """Tier 2: best fuzzy_similarity() over every candidate description.

    The single best match wins and its ratio is the confidence. There is
    deliberately no floor: a low-scoring match is still returned, with its
    low confidence, for the caller to judge. max() returns the first maximal
    element and candidates are id-descending, so an exact ratio tie resolves
    to the highest id. `needle` is already casefolded; fuzzy_similarity
    casefolds again, which is idempotent, so the scores are exactly what the
    Session 41 inline version gave.
    """
    best = max(candidates, key=lambda row: fuzzy_similarity(needle, row["description"]))
    ratio = fuzzy_similarity(needle, best["description"])
    return {"value": best[field], "confidence": ratio, "match_type": "fuzzy"}


def _suggest_category_from(
    target_id: int, description: str, labeled: "list[sqlite3.Row]"
) -> dict:
    """The two-tier category engine, over the already-fetched labelled rows.

    Returns {"value": str | None, "confidence": float, "match_type": str}
    where match_type is "exact", "fuzzy", or "none". (The key was "category"
    until Session 53 reshaped the response to carry a subcategory too.)

    Candidates are the OTHER rows with a category -- the target itself is
    skipped, so a transaction that already has a category does not simply
    suggest its own value back. `labeled` must be id-descending (as
    `_fetch_labeled` returns it) -- the tie-break relies on that order.

    Tier 1 is `_exact_tier`, Tier 2 (only when Tier 1 finds nothing) is
    `_fuzzy_tier`, both on the `category` field; the merchant engine shares
    them. Tie-break (both tiers): the candidate with the highest transaction
    id. The prompt that specified this engine asked for "most recently
    assigned", but the schema records no assignment time, so the highest id
    -- most recently *imported* -- is the proxy. Documented in DATA_MODEL.md.

    Cold start (no other categorized transaction exists): match_type "none".
    """
    candidates = [row for row in labeled if row["id"] != target_id and row["category"] is not None]
    if not candidates:
        return _no_suggestion()
    needle = description.casefold()
    return _exact_tier(needle, candidates, "category") or _fuzzy_tier(needle, candidates, "category")


def _suggest_merchant_from(
    target_id: int, description: str, labeled: "list[sqlite3.Row]"
) -> dict:
    """Merchant engine: category's two tiers on the `merchant` field, plus a
    fallback tier category does not have. Never returns "none".

    Candidates are the OTHER rows with a merchant -- global, not scoped by
    category (unlike subcategory). Tier 1 exact and Tier 2 fuzzy are the
    shared helpers. Tier 3 (nothing matched -- including a true cold start
    with no merchant-bearing row anywhere) suggests the transaction's own
    raw description, match_type "from_description", confidence None: a
    default, not a learned match, so no percentage is reported and the
    frontend labels it in words. Normalization (Title Case) happens at the
    API when the value is written, not here.
    """
    candidates = [row for row in labeled if row["id"] != target_id and row["merchant"] is not None]
    if candidates:
        needle = description.casefold()
        return _exact_tier(needle, candidates, "merchant") or _fuzzy_tier(
            needle, candidates, "merchant"
        )
    return {"value": description, "confidence": None, "match_type": "from_description"}


def _suggest_subcategory_from(
    target_id: int,
    description: str,
    category: "str | None",
    merchant: "str | None",
    labeled: "list[sqlite3.Row]",
) -> "dict | None":
    """Subcategory suggestion -- deliberately simpler than category's. No fuzzy tier.

    - Category not yet set on the row -> None (the API renders it as null):
      subcategory suggestion does not run until the row has a category.
    - Tier 1 "exact": peers are OTHER rows with the same category (case-
      insensitive), a non-null subcategory, and an exactly matching
      description (casefold equality, nothing else normalised -- category
      Tier 1's rule). If any: most frequent subcategory wins, confidence is
      its share, ties break to the highest id via the same id-DESC ordering
      + Counter.most_common() first-seen trick as Tier 1.
    - Tier 2 "merchant_category" (Session 88): only when the row has a
      merchant and Tier 1 found nothing. Precedents are OTHER rows whose
      merchant and category both match the target's (case-insensitive --
      the cascade stores "HDFC" where a manual write stores "Hdfc", and
      those are one merchant) and whose subcategory is set. How the
      precedent got its labels (manual, bulk, cascade) and whether it is a
      debit or a credit are irrelevant; only the three columns count. Same
      majority-vote and highest-id tie-break as Tier 1; confidence is the
      winner's share of the precedents and the extra key "precedents" is
      how many there were, so a 1-of-1 and a 12-of-12 both read 1.0 but
      the frontend can show the difference. This is learned evidence, so
      it is bulk-acceptable, unlike the tier below.
    - Tier 3 "same_as_category": nothing above matched (including a
      category nobody has sub-labelled yet) -> the row's own category
      value, confidence 1.0. That 1.0 is a default, not a learned match;
      the frontend labels it in words rather than as a percentage for
      exactly that reason, and bulk accept skips it.
    """
    if category is None:
        return None
    needle = description.casefold()
    wanted = category.casefold()
    # `labeled` has held merchant-only rows (category NULL) since Session
    # 55, and a subcategory-only write can give one a subcategory; the
    # `is not None` guard before each casefold is the category and merchant
    # engines' convention for exactly that pool (Session 91).
    peers = [
        row
        for row in labeled
        if row["id"] != target_id
        and row["subcategory"] is not None
        and row["category"] is not None
        and row["category"].casefold() == wanted
        and row["description"].casefold() == needle
    ]
    if peers:
        counts = Counter(row["subcategory"] for row in peers)
        value, count = counts.most_common(1)[0]
        return {"value": value, "confidence": count / len(peers), "match_type": "exact"}
    if merchant is not None:
        wanted_merchant = merchant.casefold()
        precedents = [
            row
            for row in labeled
            if row["id"] != target_id
            and row["subcategory"] is not None
            and row["category"] is not None
            and row["category"].casefold() == wanted
            and row["merchant"] is not None
            and row["merchant"].casefold() == wanted_merchant
        ]
        if precedents:
            counts = Counter(row["subcategory"] for row in precedents)
            value, count = counts.most_common(1)[0]
            return {
                "value": value,
                "confidence": count / len(precedents),
                "match_type": "merchant_category",
                "precedents": len(precedents),
            }
    return {"value": category, "confidence": 1.0, "match_type": "same_as_category"}


def _suggest_from(target: sqlite3.Row, labeled: "list[sqlite3.Row]") -> dict:
    """All three suggestions for one target row, in the response shape:
    {"category": {...}, "subcategory": {...} | None, "merchant": {...}}."""
    return {
        "category": _suggest_category_from(target["id"], target["description"], labeled),
        "subcategory": _suggest_subcategory_from(
            target["id"], target["description"], target["category"], target["merchant"], labeled
        ),
        "merchant": _suggest_merchant_from(target["id"], target["description"], labeled),
    }


def suggest_category(conn: sqlite3.Connection, transaction_id: int) -> dict:
    """Suggest a category, subcategory, and merchant for one transaction.

    Category search is global over every OTHER categorized transaction --
    all cards, all statements; see `_suggest_category_from`. Subcategory
    follows `_suggest_subcategory_from`. Returns
    {"category": {value, confidence, match_type},
     "subcategory": {value, confidence, match_type} | None,
     "merchant": {value, confidence, match_type}}.
    """
    targets = _fetch_targets(conn, [transaction_id])
    return _suggest_from(targets[transaction_id], _fetch_labeled(conn))


def suggest_categories_for_descriptions(
    conn: sqlite3.Connection, descriptions: "list[str]"
) -> "list[dict]":
    """The category engine over descriptions that are NOT in the database.

    For the upload preview (Session 103): the parsed rows have no
    transaction id yet, so `suggest_category` -- which fetches its target by
    id -- cannot run on them. This runs the same two-tier engine
    (`_suggest_category_from`) over the same labelled rows, fetched once for
    the whole list, with no target to exclude (target_id None matches no
    row). Read-only; nothing is written and nothing is cached. Returns one
    {"value", "confidence", "match_type"} per description, in order --
    match_type "none" where the engine has nothing to say.
    """
    labeled = _fetch_labeled(conn)
    return [_suggest_category_from(None, description, labeled) for description in descriptions]


def suggest_categories(conn: sqlite3.Connection, transaction_ids: "list[int]") -> "list[dict]":
    """Suggestions for each listed transaction, in input order.

    Returns one dict per distinct id, each the single-id shape plus a
    "transaction_id" key. The labelled-transaction query runs exactly
    once for the whole batch, however many ids are given; that is the point
    of this function over N calls to `suggest_category`.

    All-or-nothing on existence: any unknown id raises
    TransactionNotFoundError before anything is computed. Duplicate ids
    are collapsed (first occurrence keeps its position).
    """
    ids = list(dict.fromkeys(transaction_ids))
    if not ids:
        raise ValueError("transaction_ids must not be empty")
    targets = _fetch_targets(conn, ids)
    labeled = _fetch_labeled(conn)
    return [{"transaction_id": i, **_suggest_from(targets[i], labeled)} for i in ids]


def cluster_by_similarity(
    items: "list[tuple[int, str]]", threshold: "int | float"
) -> "list[dict]":
    """Anchor-based clustering of (id, description) pairs by fuzzy similarity.

    `threshold` is 0-100, a percentage of fuzzy_similarity()'s 0-1 ratio; a
    pair joins when ratio >= threshold / 100 (so 70 admits exactly 0.70).

    Walk the list in the order given. Each not-yet-clustered item becomes
    the anchor of a new cluster; every later not-yet-clustered item whose
    similarity *to that anchor* meets the threshold joins it, in list order.
    Membership is decided against the anchor only -- not transitively, not
    against other members -- so the outcome depends on the input order,
    which is why the caller's order is respected rather than re-sorted.

    Returns only clusters of two or more, each as
        {"anchor_id": id, "members": [{"transaction_id": id, "similarity": 0-100}, ...]}
    with the anchor first (its own similarity is exactly 100.0) and every
    other member carrying the same anchor-comparison score that admitted it
    -- the value is exposed, not recomputed (Session 52). A singleton is
    dropped entirely: not returned, not bucketed. Duplicate ids are collapsed
    to their first occurrence. Pure function, no database access; the
    endpoint resolves descriptions.
    """
    seen = set()
    ordered = []
    for item in items:
        if item[0] not in seen:
            seen.add(item[0])
            ordered.append(item)

    cutoff = threshold / 100
    clustered = set()
    clusters = []
    for i, (anchor_id, anchor_desc) in enumerate(ordered):
        if anchor_id in clustered:
            continue
        clustered.add(anchor_id)
        members = [{"transaction_id": anchor_id, "similarity": 100.0}]
        for other_id, other_desc in ordered[i + 1 :]:
            if other_id in clustered:
                continue
            ratio = fuzzy_similarity(anchor_desc, other_desc)
            if ratio >= cutoff:
                clustered.add(other_id)
                members.append({"transaction_id": other_id, "similarity": ratio * 100})
        if len(members) >= 2:
            clusters.append({"anchor_id": anchor_id, "members": members})
    return clusters


def cluster_transactions(
    conn: sqlite3.Connection, transaction_ids: "list[int]", threshold: "int | float"
) -> "list[dict]":
    """cluster_by_similarity over real rows: resolves descriptions by id.

    Empty input -> empty result. Any unknown id -> TransactionNotFoundError,
    nothing computed, matching the other id-taking endpoints.
    """
    ids = list(dict.fromkeys(transaction_ids))
    if not ids:
        return []
    targets = _fetch_targets(conn, ids)
    return cluster_by_similarity([(i, targets[i]["description"]) for i in ids], threshold)


PAYMENT_LABEL = "Credit Card Payment"


class InvalidPaymentFlagError(Exception):
    """Raised when is_payment=1 is requested for a transaction that is not a credit.

    A payment to the card can only ever be a credit line; flagging a debit as
    one is semantically invalid, not merely unusual, so it is rejected (the
    API maps this to 400) and nothing in the request is written.
    """

    def __init__(self, invalid_ids: "list[int]"):
        self.invalid_ids = invalid_ids
        super().__init__(f"is_payment can only be set on credit transactions: {invalid_ids}")


def assign_categories(
    conn: sqlite3.Connection,
    assignments: "list[tuple[int, str | None, str | None, str | None, bool | None]]",
) -> int:
    """Write each (transaction_id, category, subcategory, merchant, is_payment)
    entry, in one transaction.

    A None field means "leave that column as it is"; only the fields present
    are written, unconditionally overwriting whatever was there (Session 53
    -- until then every pair carried a category). Returns the number of
    distinct transactions updated. A uniform assignment is just N entries
    with the same values; a mixed one (accepting several different
    suggestions at once) is N entries with different values -- either way
    one call, one SQL transaction.

    All-or-nothing: if any id does not exist, TransactionNotFoundError is
    raised and nothing is written -- a bulk assign must never partially
    apply (the Session 17 invariant). The existence check, the payment-flag
    checks, and the UPDATEs share one `with conn:` block so a row can't
    change between them.

    Rules on the input:
    - An entry with no field at all raises ValueError.
    - Identical duplicate entries collapse and count once. Two entries for
      the same id that both set the same field to *different* values raise
      ValueError rather than resolving by position: that can only be a
      client bug, and last-wins would hide it. Two entries for the same id
      setting *different* fields are merged into one row update.
    - A present text field must be a non-empty string; NULL is the only
      representation of "unset" and this function never writes an empty
      string for a label. The caller is expected to have stripped/normalised
      (the API layer does).

    is_payment (Session 61) is a boolean with a cascade, resolved inside the
    transaction against the row's current state:
    - is_payment=True on a non-credit row -> InvalidPaymentFlagError, nothing
      written for the whole request.
    - Same value as already stored -> no-op for that field; the cascade is
      not re-triggered and the row is not counted unless another field
      changes it.
    - 0 -> 1 also writes category and subcategory = PAYMENT_LABEL and
      merchant = the card's bank name (via statement -> card), overwriting
      whatever those held. The bank name is written as stored on the card,
      not Title-Cased: "HDFC" must not become "Hdfc".
    - 1 -> 0 reverts category, subcategory, and merchant to NULL, handing the
      row back to the normal suggestion flow.
    - A cascade value and an explicit value for the same field in one entry
      go through the same conflict rule: equal is fine, different is a
      ValueError.
    """
    if not assignments:
        raise ValueError("assignments must not be empty")

    # id -> {column: value} for the explicit fields present. Text labels are
    # str; is_payment is bool and is resolved below once current state is
    # known.
    by_id: "dict[int, dict]" = {}

    def merge(transaction_id: int, column: str, value) -> None:
        merged = by_id.setdefault(transaction_id, {})
        previous = merged.setdefault(column, value)
        if previous != value:
            raise ValueError(
                f"transaction {transaction_id} assigned conflicting {column} values: "
                f"{previous!r} and {value!r}"
            )

    for transaction_id, category, subcategory, merchant, is_payment in assignments:
        fields = {}
        if category is not None:
            fields["category"] = category
        if subcategory is not None:
            fields["subcategory"] = subcategory
        if merchant is not None:
            fields["merchant"] = merchant
        if is_payment is not None:
            fields["is_payment"] = bool(is_payment)
        if not fields:
            raise ValueError(
                f"transaction {transaction_id}: at least one of category, subcategory, "
                "merchant, or is_payment is required"
            )
        for column, value in fields.items():
            if column != "is_payment" and not value:
                raise ValueError(f"{column} must be a non-empty string")
        by_id.setdefault(transaction_id, {})
        for column, value in fields.items():
            merge(transaction_id, column, value)

    ids = sorted(by_id)
    placeholders = ",".join("?" * len(ids))
    with conn:
        rows = conn.execute(
            "SELECT t.id, t.txn_type, t.is_payment, c.bank "
            "FROM transactions t "
            "JOIN statements s ON t.statement_id = s.id "
            "JOIN cards c ON s.card_id = c.id "
            f"WHERE t.id IN ({placeholders})",
            ids,
        ).fetchall()
        current = {row["id"]: row for row in rows}
        missing = [i for i in ids if i not in current]
        if missing:
            raise TransactionNotFoundError(missing)

        # Resolve the payment flag against current state: reject invalid,
        # drop no-ops, expand the cascade -- all before any UPDATE, so an
        # invalid entry anywhere in the request leaves nothing written.
        invalid = []
        for transaction_id, fields in by_id.items():
            if "is_payment" not in fields:
                continue
            wanted = fields.pop("is_payment")
            row = current[transaction_id]
            if wanted and row["txn_type"] != "credit":
                invalid.append(transaction_id)
                continue
            if wanted == bool(row["is_payment"]):
                continue  # no-op: same value, no cascade
            if wanted:
                cascade = {
                    "is_payment": 1,
                    "category": PAYMENT_LABEL,
                    "subcategory": PAYMENT_LABEL,
                    "merchant": row["bank"],
                }
            else:
                cascade = {
                    "is_payment": 0,
                    "category": None,
                    "subcategory": None,
                    "merchant": None,
                }
            for column, value in cascade.items():
                merge(transaction_id, column, value)
        if invalid:
            raise InvalidPaymentFlagError(sorted(invalid))

        # One UPDATE per distinct (fields, values) combination, not per row:
        # the common case (accept a whole suggestion group, or assign one
        # typed value) is still a single statement. Entries left with no
        # field (a pure no-op flag) write nothing and are not counted.
        by_update: "dict[tuple, list[int]]" = {}
        for transaction_id, fields in by_id.items():
            if not fields:
                continue
            key = tuple(sorted(fields.items(), key=lambda kv: kv[0]))
            by_update.setdefault(key, []).append(transaction_id)
        updated = 0
        for key, group in by_update.items():
            set_sql = ", ".join(f"{column} = ?" for column, _ in key)
            values = [value for _, value in key]
            marks = ",".join("?" * len(group))
            cursor = conn.execute(
                f"UPDATE transactions SET {set_sql} WHERE id IN ({marks})",
                [*values, *group],
            )
            updated += cursor.rowcount
    return updated


def _catalog(
    conn: sqlite3.Connection,
    column: str,
    *,
    scope_sql: str = "",
    scope_params: "list | None" = None,
    **filters,
) -> "list[str]":
    """Sorted distinct non-null values of one label column, narrowed by the
    shared read-path filters (Session 75). `scope_sql`/`scope_params` carry
    an endpoint's own extra clause (list_subcategories' category scoping),
    kept verbatim so pre-existing behaviour does not shift."""
    from storage.reads import filter_sql  # reads is the lower layer

    joins, where, params = filter_sql("transactions", **filters)
    conditions = [f"transactions.{column} IS NOT NULL"]
    if scope_sql:
        conditions.append(scope_sql)
    extra = " AND ".join(conditions)
    where = (where + " AND " if where else " WHERE ") + extra
    rows = conn.execute(
        f"SELECT DISTINCT transactions.{column} AS value FROM transactions"
        + joins + where + f" ORDER BY transactions.{column}",
        [*params, *(scope_params or [])],
    ).fetchall()
    return [row["value"] for row in rows]


def list_categories(
    conn: sqlite3.Connection,
    bank: "str | None" = None,
    card_id: "int | None" = None,
    card_type: "str | None" = None,
    statement_month: "str | None" = None,
    start_date=None,
    end_date=None,
) -> "list[str]":
    """Sorted distinct category values currently in use on transactions.

    There is no predefined category list anywhere in the system; this is
    the only source of "categories you've used before", and it feeds the
    frontend's dropdown/typeahead. Empty until the first assignment.

    Narrowable by bank / card / card type / statement month / date range
    (Session 75) so the picker shows only categories with data under the
    other filters. Deliberately NOT narrowable by subcategory or merchant:
    the three labels are independent peers in the filter bar, not a
    cascade, so none of their option lists narrows another's.
    """
    return _catalog(
        conn, "category",
        bank=bank, card_id=card_id, card_type=card_type,
        statement_month=statement_month, start_date=start_date, end_date=end_date,
    )


def list_subcategories(
    conn: sqlite3.Connection,
    category: "str | None" = None,
    bank: "str | None" = None,
    card_id: "int | None" = None,
    card_type: "str | None" = None,
    statement_month: "str | None" = None,
    start_date=None,
    end_date=None,
) -> "list[str]":
    """Sorted distinct subcategory values in use, optionally within one category.

    Same role for subcategory as list_categories() has for category. The
    `category` scope predates Session 75 and serves the review screen's
    per-row editor: an exact match on the stored value (values are
    Title-Cased on write, so exact is case-insensitive in practice), kept
    verbatim -- it is not the filter-bar narrowing, and it deliberately
    stays the only label that scopes this list. The bank / card / card
    type / month / date narrowing (Session 75) is the filter-bar mesh; no
    merchant scoping, by design.
    """
    scope_sql, scope_params = ("transactions.category = ?", [category]) if category is not None else ("", [])
    return _catalog(
        conn, "subcategory", scope_sql=scope_sql, scope_params=scope_params,
        bank=bank, card_id=card_id, card_type=card_type,
        statement_month=statement_month, start_date=start_date, end_date=end_date,
    )


def list_merchants(
    conn: sqlite3.Connection,
    bank: "str | None" = None,
    card_id: "int | None" = None,
    card_type: "str | None" = None,
    statement_month: "str | None" = None,
    start_date=None,
    end_date=None,
) -> "list[str]":
    """Sorted distinct merchant values in use. Never scoped by category or
    subcategory (merchant matching is global, and the three labels don't
    narrow each other); narrowable by the filter-bar mesh (Session 75)."""
    return _catalog(
        conn, "merchant",
        bank=bank, card_id=card_id, card_type=card_type,
        statement_month=statement_month, start_date=start_date, end_date=end_date,
    )
