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


def _fetch_categorized(conn: sqlite3.Connection) -> "list[sqlite3.Row]":
    """Every categorized transaction, id-descending.

    This is the one query behind both suggestion entry points. The batch
    path runs it once and reuses the rows for every id in the request;
    the self-exclusion that used to be `id != ?` in SQL is now done in
    `_suggest_from()` so the same row set can serve many targets.

    Comparisons happen in Python rather than SQL because SQLite's
    LOWER()/NOCASE are ASCII-only while str.casefold() is Unicode-aware,
    and Tier 2 has to happen in Python anyway -- so one code path with one
    definition of "case-insensitive".
    """
    return conn.execute(
        "SELECT id, description, category, subcategory FROM transactions "
        "WHERE category IS NOT NULL ORDER BY id DESC"
    ).fetchall()


def _fetch_targets(conn: sqlite3.Connection, transaction_ids: "list[int]") -> "dict[int, sqlite3.Row]":
    """id -> row (id, description, category) for the given ids; raises if any is unknown."""
    placeholders = ",".join("?" * len(transaction_ids))
    rows = conn.execute(
        f"SELECT id, description, category FROM transactions WHERE id IN ({placeholders})",
        transaction_ids,
    ).fetchall()
    found = {row["id"]: row for row in rows}
    missing = [i for i in transaction_ids if i not in found]
    if missing:
        raise TransactionNotFoundError(missing)
    return found


def _suggest_category_from(
    target_id: int, description: str, categorized: "list[sqlite3.Row]"
) -> dict:
    """The two-tier category engine, over an already-fetched candidate list.

    Returns {"value": str | None, "confidence": float, "match_type": str}
    where match_type is "exact", "fuzzy", or "none". (The key was "category"
    until Session 53 reshaped the response to carry a subcategory too.)

    `categorized` must be id-descending (as `_fetch_categorized` returns
    it) -- the tie-break relies on that order. The target itself is
    skipped here, so a transaction that already has a category does not
    simply suggest its own value back.

    Tier 1 (exact): case-insensitive equality on description. No other
    normalization (whitespace, digits, punctuation are compared as-is); this
    is a decision, not an oversight -- see DEVLOG Session 41. If the matches
    span several categories, the most frequent wins; confidence is that
    category's share of the exact matches (1.0 when they all agree), so a
    50/50 split reports 0.5 rather than a misleading 1.0.

    Tier 2 (fuzzy, only when Tier 1 finds nothing): difflib.SequenceMatcher
    ratio() against every other categorized description, case-folded on
    both sides so a case difference does not depress the score when Tier 1
    already treats case as irrelevant. The single best match wins and its
    ratio is the confidence. There is deliberately no floor: a low-scoring
    match is still returned, with its low confidence, for the caller to
    judge.

    Tie-break (both tiers): the candidate with the highest transaction id.
    The prompt that specified this engine asked for "most recently
    assigned", but the schema records no assignment time, so the highest id
    -- most recently *imported* -- is the proxy. Documented in DATA_MODEL.md.

    Cold start (no other categorized transaction exists): match_type "none".
    """
    candidates = [row for row in categorized if row["id"] != target_id]
    if not candidates:
        return _no_suggestion()

    needle = description.casefold()

    # Tier 1. Candidates arrive id-descending, so the first hit per category
    # is that category's most recent one; Counter.most_common() preserves
    # first-seen order among equal counts, which makes the tie-break fall
    # out of the ordering rather than needing a second sort key.
    exact = [row for row in candidates if row["description"].casefold() == needle]
    if exact:
        counts = Counter(row["category"] for row in exact)
        category, count = counts.most_common(1)[0]
        return {
            "value": category,
            "confidence": count / len(exact),
            "match_type": "exact",
        }

    # Tier 2. max() returns the first maximal element, and candidates are
    # id-descending, so an exact ratio tie again resolves to the highest id.
    # `needle` is already casefolded; fuzzy_similarity casefolds again, which
    # is idempotent, so the scores are exactly what the inline version gave.
    best = max(
        candidates,
        key=lambda row: fuzzy_similarity(needle, row["description"]),
    )
    ratio = fuzzy_similarity(needle, best["description"])
    return {"value": best["category"], "confidence": ratio, "match_type": "fuzzy"}


def _suggest_subcategory_from(
    target_id: int,
    description: str,
    category: "str | None",
    categorized: "list[sqlite3.Row]",
) -> "dict | None":
    """Subcategory suggestion -- deliberately simpler than category's. No fuzzy tier.

    - Category not yet set on the row -> None (the API renders it as null):
      subcategory suggestion does not run until the row has a category.
    - Otherwise, peers are OTHER rows with the same category (case-
      insensitive), a non-null subcategory, and an exactly matching
      description (casefold equality, nothing else normalised -- category
      Tier 1's rule). If any: most frequent subcategory wins, confidence is
      its share, ties break to the highest id via the same id-DESC ordering
      + Counter.most_common() first-seen trick as Tier 1. match_type "exact".
    - No peers (including a category nobody has sub-labelled yet) -> the
      row's own category value, match_type "same_as_category", confidence
      1.0. That 1.0 is a default, not a learned match; the frontend labels
      it in words rather than as a percentage for exactly that reason.
    """
    if category is None:
        return None
    needle = description.casefold()
    wanted = category.casefold()
    peers = [
        row
        for row in categorized
        if row["id"] != target_id
        and row["subcategory"] is not None
        and row["category"].casefold() == wanted
        and row["description"].casefold() == needle
    ]
    if peers:
        counts = Counter(row["subcategory"] for row in peers)
        value, count = counts.most_common(1)[0]
        return {"value": value, "confidence": count / len(peers), "match_type": "exact"}
    return {"value": category, "confidence": 1.0, "match_type": "same_as_category"}


def _suggest_from(target: sqlite3.Row, categorized: "list[sqlite3.Row]") -> dict:
    """Both suggestions for one target row, in the response shape:
    {"category": {...}, "subcategory": {...} | None}."""
    return {
        "category": _suggest_category_from(target["id"], target["description"], categorized),
        "subcategory": _suggest_subcategory_from(
            target["id"], target["description"], target["category"], categorized
        ),
    }


def suggest_category(conn: sqlite3.Connection, transaction_id: int) -> dict:
    """Suggest a category and subcategory for one transaction.

    Category search is global over every OTHER categorized transaction --
    all cards, all statements; see `_suggest_category_from`. Subcategory
    follows `_suggest_subcategory_from`. Returns
    {"category": {value, confidence, match_type},
     "subcategory": {value, confidence, match_type} | None}.
    """
    targets = _fetch_targets(conn, [transaction_id])
    return _suggest_from(targets[transaction_id], _fetch_categorized(conn))


def suggest_categories(conn: sqlite3.Connection, transaction_ids: "list[int]") -> "list[dict]":
    """Suggestions for each listed transaction, in input order.

    Returns one dict per distinct id, each the single-id shape plus a
    "transaction_id" key. The categorized-transaction query runs exactly
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
    categorized = _fetch_categorized(conn)
    return [{"transaction_id": i, **_suggest_from(targets[i], categorized)} for i in ids]


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


def assign_categories(
    conn: sqlite3.Connection,
    assignments: "list[tuple[int, str | None, str | None]]",
) -> int:
    """Write each (transaction_id, category, subcategory) triple, in one transaction.

    A None field means "leave that column as it is"; only the fields present
    are written, unconditionally overwriting whatever was there (Session 53
    -- until then every pair carried a category). Returns the number of
    distinct transactions updated. A uniform assignment is just N triples
    with the same values; a mixed one (accepting several different
    suggestions at once) is N triples with different values -- either way
    one call, one SQL transaction.

    All-or-nothing: if any id does not exist, TransactionNotFoundError is
    raised and nothing is written -- a bulk assign must never partially
    apply (the Session 17 invariant). The existence check and the UPDATEs
    share one `with conn:` block so a row can't vanish between them.

    Rules on the input:
    - A triple with neither field raises ValueError.
    - Identical duplicate triples collapse and count once. Two triples for
      the same id that both set the same field to *different* values raise
      ValueError rather than resolving by position: that can only be a
      client bug, and last-wins would hide it. Two triples for the same id
      setting *different* fields are merged into one row update.
    - A present field must be a non-empty string; NULL is the only
      representation of "unset" and this function never writes an empty
      string. The caller is expected to have stripped/normalised (the API
      layer does).
    """
    if not assignments:
        raise ValueError("assignments must not be empty")

    # id -> {"category": ..., "subcategory": ...} for the fields present.
    by_id: "dict[int, dict[str, str]]" = {}
    for transaction_id, category, subcategory in assignments:
        fields = {}
        if category is not None:
            fields["category"] = category
        if subcategory is not None:
            fields["subcategory"] = subcategory
        if not fields:
            raise ValueError(
                f"transaction {transaction_id}: at least one of category or subcategory is required"
            )
        for column, value in fields.items():
            if not value:
                raise ValueError(f"{column} must be a non-empty string")
        merged = by_id.setdefault(transaction_id, {})
        for column, value in fields.items():
            previous = merged.setdefault(column, value)
            if previous != value:
                raise ValueError(
                    f"transaction {transaction_id} assigned conflicting {column} values: "
                    f"{previous!r} and {value!r}"
                )

    ids = sorted(by_id)
    placeholders = ",".join("?" * len(ids))
    with conn:
        found = {
            row["id"]
            for row in conn.execute(
                f"SELECT id FROM transactions WHERE id IN ({placeholders})", ids
            )
        }
        missing = [i for i in ids if i not in found]
        if missing:
            raise TransactionNotFoundError(missing)

        # One UPDATE per distinct (fields, values) combination, not per row:
        # the common case (accept a whole suggestion group, or assign one
        # typed value) is still a single statement.
        by_update: "dict[tuple, list[int]]" = {}
        for transaction_id, fields in by_id.items():
            key = tuple(sorted(fields.items()))
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


def list_categories(conn: sqlite3.Connection) -> "list[str]":
    """Sorted distinct category values currently in use on transactions.

    There is no predefined category list anywhere in the system; this is
    the only source of "categories you've used before", and it feeds the
    frontend's dropdown/typeahead. Empty until the first assignment.
    """
    rows = conn.execute(
        "SELECT DISTINCT category FROM transactions "
        "WHERE category IS NOT NULL ORDER BY category"
    ).fetchall()
    return [row["category"] for row in rows]


def list_subcategories(conn: sqlite3.Connection, category: "str | None" = None) -> "list[str]":
    """Sorted distinct subcategory values in use, optionally within one category.

    Same role for subcategory as list_categories() has for category: there
    is no predefined list, so this is the only source of "subcategories
    you've used before". With `category`, only rows carrying that exact
    category value are considered (values are Title-Cased on write, so an
    exact comparison is a case-insensitive one in practice).
    """
    sql = "SELECT DISTINCT subcategory FROM transactions WHERE subcategory IS NOT NULL"
    params: list = []
    if category is not None:
        sql += " AND category = ?"
        params.append(category)
    rows = conn.execute(sql + " ORDER BY subcategory", params).fetchall()
    return [row["subcategory"] for row in rows]
