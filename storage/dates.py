from datetime import date


def to_date_str(value):
    """Normalize a date value for storage/query binding.

    date objects become ISO strings (YYYY-MM-DD); anything else (e.g. an
    already-ISO string) passes through unchanged.
    """
    return value.isoformat() if isinstance(value, date) else value
