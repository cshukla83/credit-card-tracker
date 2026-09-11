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


def _no_suggestion() -> dict:
    return {"category": None, "confidence": 0.0, "match_type": "none"}


def suggest_category(conn: sqlite3.Connection, transaction_id: int) -> dict:
    """Suggest a category for one transaction from every OTHER categorized one.

    Returns {"category": str | None, "confidence": float, "match_type": str}
    where match_type is "exact", "fuzzy", or "none".

    Search is global -- all cards, all statements -- and never includes the
    target transaction itself, so a transaction that already has a category
    does not simply suggest its own value back.

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
    target = conn.execute(
        "SELECT description FROM transactions WHERE id = ?", (transaction_id,)
    ).fetchone()
    if target is None:
        raise TransactionNotFoundError([transaction_id])

    # One query feeds both tiers. Both comparisons are done in Python rather
    # than SQL because SQLite's LOWER()/NOCASE are ASCII-only while
    # str.casefold() is Unicode-aware, and Tier 2 has to happen in Python
    # anyway -- so one code path with one definition of "case-insensitive".
    candidates = conn.execute(
        "SELECT id, description, category FROM transactions "
        "WHERE category IS NOT NULL AND id != ? "
        "ORDER BY id DESC",
        (transaction_id,),
    ).fetchall()
    if not candidates:
        return _no_suggestion()

    needle = target["description"].casefold()

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
    best = max(
        candidates,
        key=lambda row: SequenceMatcher(None, needle, row["description"].casefold()).ratio(),
    )
    ratio = SequenceMatcher(None, needle, best["description"].casefold()).ratio()
    return {"category": best["category"], "confidence": ratio, "match_type": "fuzzy"}


def assign_category(
    conn: sqlite3.Connection, transaction_ids: "list[int]", category: str
) -> int:
    """Set category on every listed transaction, unconditionally, in one transaction.

    Overwrites any existing category. Returns the number of rows updated
    (duplicate ids in the input count once, since it's one UPDATE).

    All-or-nothing: if any id does not exist, TransactionNotFoundError is
    raised and nothing is written -- a bulk assign must never partially
    apply (the Session 17 invariant). The existence check and the UPDATE
    share one `with conn:` block so a row can't vanish between them.

    `category` must be a non-empty string; NULL is the only representation
    of "uncategorized" and this function never writes an empty string. The
    caller is expected to have stripped/validated it (the API layer does).
    """
    if not category:
        raise ValueError("category must be a non-empty string")
    ids = sorted(set(transaction_ids))
    if not ids:
        raise ValueError("transaction_ids must not be empty")

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

        cursor = conn.execute(
            f"UPDATE transactions SET category = ? WHERE id IN ({placeholders})",
            [category, *ids],
        )
    return cursor.rowcount
