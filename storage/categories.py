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
    return {"category": None, "confidence": 0.0, "match_type": "none"}


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
        "SELECT id, description, category FROM transactions "
        "WHERE category IS NOT NULL ORDER BY id DESC"
    ).fetchall()


def _fetch_targets(conn: sqlite3.Connection, transaction_ids: "list[int]") -> "dict[int, str]":
    """id -> description for the given ids; raises if any id is unknown."""
    placeholders = ",".join("?" * len(transaction_ids))
    rows = conn.execute(
        f"SELECT id, description FROM transactions WHERE id IN ({placeholders})",
        transaction_ids,
    ).fetchall()
    found = {row["id"]: row["description"] for row in rows}
    missing = [i for i in transaction_ids if i not in found]
    if missing:
        raise TransactionNotFoundError(missing)
    return found


def _suggest_from(
    target_id: int, description: str, categorized: "list[sqlite3.Row]"
) -> dict:
    """The two-tier engine, over an already-fetched candidate list.

    Returns {"category": str | None, "confidence": float, "match_type": str}
    where match_type is "exact", "fuzzy", or "none".

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
            "category": category,
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
    return {"category": best["category"], "confidence": ratio, "match_type": "fuzzy"}


def suggest_category(conn: sqlite3.Connection, transaction_id: int) -> dict:
    """Suggest a category for one transaction from every OTHER categorized one.

    Search is global -- all cards, all statements. See `_suggest_from` for
    the engine's rules; this is the single-id entry point over it.
    """
    targets = _fetch_targets(conn, [transaction_id])
    return _suggest_from(transaction_id, targets[transaction_id], _fetch_categorized(conn))


def suggest_categories(conn: sqlite3.Connection, transaction_ids: "list[int]") -> "list[dict]":
    """Suggest a category for each listed transaction, in input order.

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
    return [
        {"transaction_id": i, **_suggest_from(i, targets[i], categorized)} for i in ids
    ]


def cluster_by_similarity(
    items: "list[tuple[int, str]]", threshold: "int | float"
) -> "list[list[int]]":
    """Anchor-based clustering of (id, description) pairs by fuzzy similarity.

    `threshold` is 0-100, a percentage of fuzzy_similarity()'s 0-1 ratio; a
    pair joins when ratio >= threshold / 100 (so 70 admits exactly 0.70).

    Walk the list in the order given. Each not-yet-clustered item becomes
    the anchor of a new cluster; every later not-yet-clustered item whose
    similarity *to that anchor* meets the threshold joins it, in list order.
    Membership is decided against the anchor only -- not transitively, not
    against other members -- so the outcome depends on the input order,
    which is why the caller's order is respected rather than re-sorted.

    Only clusters of two or more are returned, as lists of ids with the
    anchor first. A singleton is dropped entirely: not returned, not
    bucketed. Duplicate ids are collapsed to their first occurrence. Pure
    function, no database access; the endpoint resolves descriptions.
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
        members = [anchor_id]
        for other_id, other_desc in ordered[i + 1 :]:
            if other_id in clustered:
                continue
            if fuzzy_similarity(anchor_desc, other_desc) >= cutoff:
                clustered.add(other_id)
                members.append(other_id)
        if len(members) >= 2:
            clusters.append(members)
    return clusters


def cluster_transactions(
    conn: sqlite3.Connection, transaction_ids: "list[int]", threshold: "int | float"
) -> "list[list[int]]":
    """cluster_by_similarity over real rows: resolves descriptions by id.

    Empty input -> empty result. Any unknown id -> TransactionNotFoundError,
    nothing computed, matching the other id-taking endpoints.
    """
    ids = list(dict.fromkeys(transaction_ids))
    if not ids:
        return []
    descriptions = _fetch_targets(conn, ids)
    return cluster_by_similarity([(i, descriptions[i]) for i in ids], threshold)


def assign_categories(
    conn: sqlite3.Connection, assignments: "list[tuple[int, str]]"
) -> int:
    """Write each (transaction_id, category) pair, unconditionally, in one transaction.

    Overwrites any existing category. Returns the number of distinct
    transactions updated. A uniform assignment is just N pairs with the
    same category; a mixed one (accepting several different suggestions
    at once) is N pairs with different categories -- either way one call,
    one SQL transaction.

    All-or-nothing: if any id does not exist, TransactionNotFoundError is
    raised and nothing is written -- a bulk assign must never partially
    apply (the Session 17 invariant). The existence check and the UPDATEs
    share one `with conn:` block so a row can't vanish between them.

    Identical duplicate pairs collapse and count once. The same id with two
    *different* categories is rejected with ValueError rather than resolved
    by position: it can only come from a client bug, and last-wins would
    hide it.

    Every category must be a non-empty string; NULL is the only
    representation of "uncategorized" and this function never writes an
    empty string. The caller is expected to have stripped/validated (the
    API layer does).
    """
    if not assignments:
        raise ValueError("assignments must not be empty")

    by_id: "dict[int, str]" = {}
    for transaction_id, category in assignments:
        if not category:
            raise ValueError("category must be a non-empty string")
        previous = by_id.setdefault(transaction_id, category)
        if previous != category:
            raise ValueError(
                f"transaction {transaction_id} assigned conflicting categories: "
                f"{previous!r} and {category!r}"
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

        # One UPDATE per distinct category, not per row: the common case
        # (accept a whole suggestion group, or assign one typed value) is
        # still a single statement.
        by_category: "dict[str, list[int]]" = {}
        for transaction_id, category in by_id.items():
            by_category.setdefault(category, []).append(transaction_id)
        updated = 0
        for category, group in by_category.items():
            marks = ",".join("?" * len(group))
            cursor = conn.execute(
                f"UPDATE transactions SET category = ? WHERE id IN ({marks})",
                [category, *group],
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
