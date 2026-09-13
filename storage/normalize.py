"""The one Title Case rule for the three text labels (category, subcategory,
merchant), shared by the write path (main.py's validator) and the read-path
filters (storage.reads.filter_sql) since Session 74, so a filter value's
casing never has to match the stored casing exactly."""


def normalize_label(value: str) -> str:
    """strip() then str.title(); raises ValueError on empty.

    str.title() is a deliberately simple rule, not a smart title-caser: it
    capitalises after any non-letter, so "mcdonald's" becomes "Mcdonald'S"
    and "e-commerce" becomes "E-Commerce". Known and accepted (Session 49)
    -- no special-casing until a real example causes a real problem.
    """
    value = value.strip().title()
    if not value:
        raise ValueError("category must not be empty")
    return value
