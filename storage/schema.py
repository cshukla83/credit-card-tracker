CREATE_CARDS_TABLE = """
CREATE TABLE IF NOT EXISTS cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bank TEXT NOT NULL,
    card_type TEXT NOT NULL,
    nickname TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(bank, card_type, nickname)
)
"""

# strftime() has no month-name specifier, so the numeric month is mapped to
# a full capitalized name via an inline CASE. Shared between the fresh-DB
# CREATE TABLE definition and the existing-DB ALTER TABLE migration path
# (see db.py) so both produce byte-identical column definitions.
STATEMENT_MONTH_EXPRESSION = """
CASE CAST(strftime('%m', period_end) AS INTEGER)
    WHEN 1 THEN 'January' WHEN 2 THEN 'February' WHEN 3 THEN 'March'
    WHEN 4 THEN 'April' WHEN 5 THEN 'May' WHEN 6 THEN 'June'
    WHEN 7 THEN 'July' WHEN 8 THEN 'August' WHEN 9 THEN 'September'
    WHEN 10 THEN 'October' WHEN 11 THEN 'November' WHEN 12 THEN 'December'
END || '-' || strftime('%Y', period_end)
"""

CREATE_STATEMENTS_TABLE = f"""
CREATE TABLE IF NOT EXISTS statements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id INTEGER NOT NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    imported_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    statement_month TEXT GENERATED ALWAYS AS ({STATEMENT_MONTH_EXPRESSION}) VIRTUAL,
    FOREIGN KEY(card_id) REFERENCES cards(id) ON DELETE CASCADE,
    UNIQUE(card_id, period_start, period_end)
)
"""

# VIRTUAL, not STORED: empirically, SQLite's ALTER TABLE ADD COLUMN refuses
# to add a STORED generated column to a table that already has rows
# ("cannot add a STORED column") -- exactly the case for any DB from before
# this session. VIRTUAL has no such restriction, since it's computed on
# read rather than backfilled at ALTER time. Kept identical to the
# CREATE TABLE definition above so fresh and migrated DBs never diverge.
ADD_STATEMENT_MONTH_COLUMN = f"""
ALTER TABLE statements
ADD COLUMN statement_month TEXT GENERATED ALWAYS AS ({STATEMENT_MONTH_EXPRESSION}) VIRTUAL
"""

CREATE_TRANSACTIONS_TABLE = """
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    statement_id INTEGER NOT NULL,
    txn_date DATE NOT NULL,
    description TEXT NOT NULL,
    amount REAL NOT NULL,
    txn_type TEXT NOT NULL,
    reward_points REAL,
    category TEXT,
    subcategory TEXT,
    merchant TEXT,
    is_payment INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(statement_id) REFERENCES statements(id) ON DELETE CASCADE
)
"""

# NULL means "uncategorized" -- never an empty string. Kept identical to the
# CREATE TABLE definition above for the same reason as statement_month: a
# fresh DB and a migrated one must never diverge.
ADD_CATEGORY_COLUMN = """
ALTER TABLE transactions
ADD COLUMN category TEXT
"""

# Same rules as category: NULL means "no subcategory", never an empty string,
# and this stays identical to the CREATE TABLE column above.
ADD_SUBCATEGORY_COLUMN = """
ALTER TABLE transactions
ADD COLUMN subcategory TEXT
"""

# Same rules again: NULL means "no merchant", never an empty string, identical
# to the CREATE TABLE column above.
ADD_MERCHANT_COLUMN = """
ALTER TABLE transactions
ADD COLUMN merchant TEXT
"""

# Boolean, not tri-state: unlike the three text labels there is no "unset" --
# a credit either is a payment to the card or it isn't, and a debit never is.
# NOT NULL DEFAULT 0 is legal in ALTER TABLE ADD COLUMN (SQLite back-fills
# existing rows with the default), so a migrated DB and a fresh one agree.
ADD_IS_PAYMENT_COLUMN = """
ALTER TABLE transactions
ADD COLUMN is_payment INTEGER NOT NULL DEFAULT 0
"""
