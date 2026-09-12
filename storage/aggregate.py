"""Spend aggregation for the analytics dashboard (Session 65).

Two pieces, kept apart so each is testable on its own:

- resolve_period(): turns the API's granularity/mode parameters into one
  inclusive (start, end) date pair. Pure; "today" is injectable.
- aggregate_spend(): nets debits against refund credits per category and
  subcategory over a date range and the shared read-path filters. Payments
  to the card (is_payment = 1) are excluded entirely.
"""

import calendar
import re
import sqlite3
from datetime import date, timedelta

from storage.reads import filter_sql

GRANULARITIES = ("week", "month", "quarter", "year", "custom")
MODES = ("absolute", "relative")
UNCATEGORIZED = "Uncategorized"

_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")
_QUARTER_RE = re.compile(r"^(\d{4})-Q([1-4])$")
_YEAR_RE = re.compile(r"^(\d{4})$")


class PeriodError(ValueError):
    """An invalid or incomplete period specification (the API maps it to 422)."""


def _today() -> date:
    # Indirection so tests can pin "today" without patching the datetime module.
    return date.today()


def _shift_months(d: date, months: int) -> date:
    """`d` moved back by `months` calendar months, day clamped to the target
    month's length (31 Mar minus 1 month is 28/29 Feb)."""
    total = d.year * 12 + (d.month - 1) - months
    year, month0 = divmod(total, 12)
    last = calendar.monthrange(year, month0 + 1)[1]
    return date(year, month0 + 1, min(d.day, last))


def resolve_period(
    granularity: "str | None",
    mode: "str | None" = None,
    count: "int | None" = None,
    month: "str | None" = None,
    quarter: "str | None" = None,
    year: "str | None" = None,
    start: "str | None" = None,
    end: "str | None" = None,
    today: "date | None" = None,
) -> "tuple[date, date]":
    """Resolve the period parameters to an inclusive (start, end).

    granularity: week | month | quarter | year | custom.
    - custom: start and end (YYYY-MM-DD) required, start <= end; mode and
      count are not applicable and are rejected if given.
    - week: mode=relative only (a week has no calendar-absolute form here).
    - month / quarter / year: mode required.
      * relative: count >= 1; a rolling window ending today whose start is
        today moved back `count` units -- calendar units, not complete
        periods (month, count=3 on 15 May -> 15 Feb..15 May). week is 7*count
        days back.
      * absolute: month=YYYY-MM, quarter=YYYY-Qn, year=YYYY -> the full
        calendar period.
    Anything else raises PeriodError with a message naming the problem.
    """
    today = today or _today()

    if granularity not in GRANULARITIES:
        raise PeriodError(f"granularity must be one of {', '.join(GRANULARITIES)}")

    if granularity == "custom":
        if mode is not None or count is not None:
            raise PeriodError("mode and count are not applicable to granularity=custom")
        if not start or not end:
            raise PeriodError("granularity=custom requires start and end (YYYY-MM-DD)")
        try:
            s, e = date.fromisoformat(start), date.fromisoformat(end)
        except ValueError:
            raise PeriodError("start and end must be YYYY-MM-DD")
        if s > e:
            raise PeriodError(f"start ({s}) is after end ({e})")
        return s, e

    if mode not in MODES:
        raise PeriodError(f"granularity={granularity} requires mode=absolute or mode=relative")

    if mode == "relative":
        if count is None:
            raise PeriodError("mode=relative requires count")
        if count <= 0:
            raise PeriodError("count must be a positive integer")
        if granularity == "week":
            return today - timedelta(days=7 * count), today
        if granularity == "month":
            return _shift_months(today, count), today
        if granularity == "quarter":
            return _shift_months(today, 3 * count), today
        return _shift_months(today, 12 * count), today  # year

    # absolute
    if granularity == "week":
        raise PeriodError("granularity=week supports mode=relative only")
    if granularity == "month":
        m = _MONTH_RE.match(month or "")
        if not m or not 1 <= int(m.group(2)) <= 12:
            raise PeriodError("granularity=month with mode=absolute requires month=YYYY-MM")
        y, mo = int(m.group(1)), int(m.group(2))
        return date(y, mo, 1), date(y, mo, calendar.monthrange(y, mo)[1])
    if granularity == "quarter":
        m = _QUARTER_RE.match(quarter or "")
        if not m:
            raise PeriodError("granularity=quarter with mode=absolute requires quarter=YYYY-Qn")
        y, q = int(m.group(1)), int(m.group(2))
        first = 3 * (q - 1) + 1
        return date(y, first, 1), date(y, first + 2, calendar.monthrange(y, first + 2)[1])
    m = _YEAR_RE.match(year or "")
    if not m:
        raise PeriodError("granularity=year with mode=absolute requires year=YYYY")
    y = int(m.group(1))
    return date(y, 1, 1), date(y, 12, 31)


def aggregate_spend(
    conn: sqlite3.Connection,
    start_date: date,
    end_date: date,
    bank: "str | None" = None,
    card_id: "int | None" = None,
    card_type: "str | None" = None,
) -> dict:
    """Net spend per category and subcategory over [start_date, end_date].

    In scope: every debit, plus every credit with is_payment = 0 (a refund).
    Excluded entirely: credits with is_payment = 1 (payments to the card) --
    they appear nowhere in the result, not even as a zero line.

    amount = sum(debits) - sum(refunds); it may go negative and is not
    clamped. transaction_count is the number of contributing rows. A NULL
    category is reported as "Uncategorized"; within each category a NULL
    subcategory is likewise "Uncategorized". A row with a subcategory but
    no category therefore contributes its subcategory under the
    "Uncategorized" category (DATA_MODEL.md: the pair is not constrained).
    Categories and subcategories are sorted by amount descending. total is
    the sum of category amounts. Amounts are rounded to 2 places at the
    edge, after summing.

    Filtering is the shared read-path set (filter_sql), so bank / card_id /
    card_type mean exactly what they do on /transactions. The period is
    passed through the same helper as start_date / end_date.
    """
    joins, where, params = filter_sql(
        "transactions",
        card_id=card_id,
        bank=bank,
        card_type=card_type,
        start_date=start_date,
        end_date=end_date,
    )
    scope = "(transactions.txn_type = 'debit' OR (transactions.txn_type = 'credit' AND transactions.is_payment = 0))"
    where = (where + " AND " if where else " WHERE ") + scope
    rows = conn.execute(
        "SELECT transactions.category AS category, transactions.subcategory AS subcategory, "
        "SUM(CASE WHEN transactions.txn_type = 'debit' THEN transactions.amount "
        "ELSE -transactions.amount END) AS amount, "
        "COUNT(*) AS n "
        "FROM transactions" + joins + where + " GROUP BY transactions.category, transactions.subcategory",
        params,
    ).fetchall()

    # NULL -> "Uncategorized" is done here, not with COALESCE in SQL, so the
    # GROUP BY is on the real column values; a category literally named
    # "Uncategorized" would merge with NULL in the output either way.
    categories: "dict[str, dict]" = {}
    for row in rows:
        cat = row["category"] if row["category"] is not None else UNCATEGORIZED
        sub = row["subcategory"] if row["subcategory"] is not None else UNCATEGORIZED
        bucket = categories.setdefault(cat, {"amount": 0.0, "count": 0, "subs": {}})
        bucket["amount"] += row["amount"]
        bucket["count"] += row["n"]
        s = bucket["subs"].setdefault(sub, {"amount": 0.0, "count": 0})
        s["amount"] += row["amount"]
        s["count"] += row["n"]

    out = []
    for cat, b in categories.items():
        subs = [
            {"subcategory": sub, "amount": round(v["amount"], 2), "transaction_count": v["count"]}
            for sub, v in b["subs"].items()
        ]
        subs.sort(key=lambda x: x["amount"], reverse=True)
        out.append(
            {
                "category": cat,
                "amount": round(b["amount"], 2),
                "transaction_count": b["count"],
                "subcategories": subs,
            }
        )
    out.sort(key=lambda x: x["amount"], reverse=True)
    total = round(sum(b["amount"] for b in categories.values()), 2)
    return {
        "period": {"start": start_date.isoformat(), "end": end_date.isoformat()},
        "total": total,
        "categories": out,
    }
