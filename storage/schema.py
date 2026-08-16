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

CREATE_STATEMENTS_TABLE = """
CREATE TABLE IF NOT EXISTS statements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id INTEGER NOT NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    imported_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(card_id) REFERENCES cards(id) ON DELETE CASCADE,
    UNIQUE(card_id, period_start, period_end)
)
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
    FOREIGN KEY(statement_id) REFERENCES statements(id) ON DELETE CASCADE
)
"""
