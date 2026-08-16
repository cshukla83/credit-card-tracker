import pytest

from storage.cards import CardAlreadyExistsError, create_card, find_card, get_card, list_cards
from storage.db import get_connection, init_db

# All bank names, card types, and nicknames below are fabricated for testing.


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setenv("DB_PATH", str(path))
    init_db()
    return str(path)


def test_create_card_returns_id_and_persists(db_path):
    conn = get_connection()
    try:
        card_id = create_card(conn, "FAKE BANK", "FAKE CARD TYPE", "Primary")

        assert isinstance(card_id, int)

        row = conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        assert row["bank"] == "FAKE BANK"
        assert row["card_type"] == "FAKE CARD TYPE"
        assert row["nickname"] == "Primary"
    finally:
        conn.close()


def test_create_card_duplicate_raises(db_path):
    conn = get_connection()
    try:
        create_card(conn, "FAKE BANK", "FAKE CARD TYPE", "Primary")

        with pytest.raises(CardAlreadyExistsError):
            create_card(conn, "FAKE BANK", "FAKE CARD TYPE", "Primary")
    finally:
        conn.close()


def test_create_card_same_bank_and_type_different_nicknames_both_succeed(db_path):
    conn = get_connection()
    try:
        id_one = create_card(conn, "FAKE BANK", "FAKE CARD TYPE", "Personal")
        id_two = create_card(conn, "FAKE BANK", "FAKE CARD TYPE", "Business")

        assert id_one != id_two
    finally:
        conn.close()


def test_create_card_same_bank_and_type_both_null_nicknames_both_succeed(db_path):
    # SQLite treats each NULL as distinct for UNIQUE-constraint purposes, so
    # two unnamed cards of the same bank+card_type are allowed by design here
    # -- users who want to tell them apart can add a nickname.
    conn = get_connection()
    try:
        id_one = create_card(conn, "FAKE BANK", "FAKE CARD TYPE", None)
        id_two = create_card(conn, "FAKE BANK", "FAKE CARD TYPE", None)

        assert id_one != id_two

        rows = conn.execute(
            "SELECT COUNT(*) AS count FROM cards WHERE bank = ? AND card_type = ? AND nickname IS NULL",
            ("FAKE BANK", "FAKE CARD TYPE"),
        ).fetchone()
        assert rows["count"] == 2
    finally:
        conn.close()


def test_get_card_returns_dict(db_path):
    conn = get_connection()
    try:
        card_id = create_card(conn, "FAKE BANK", "FAKE CARD TYPE", "Primary")

        card = get_card(conn, card_id)

        assert card["id"] == card_id
        assert card["bank"] == "FAKE BANK"
        assert card["card_type"] == "FAKE CARD TYPE"
        assert card["nickname"] == "Primary"
    finally:
        conn.close()


def test_get_card_returns_none_when_missing(db_path):
    conn = get_connection()
    try:
        assert get_card(conn, 9999) is None
    finally:
        conn.close()


def test_find_card_matches_natural_key(db_path):
    conn = get_connection()
    try:
        card_id = create_card(conn, "FAKE BANK", "FAKE CARD TYPE", "Primary")

        found = find_card(conn, "FAKE BANK", "FAKE CARD TYPE", "Primary")

        assert found["id"] == card_id
    finally:
        conn.close()


def test_find_card_returns_none_when_no_match(db_path):
    conn = get_connection()
    try:
        assert find_card(conn, "FAKE BANK", "FAKE CARD TYPE", "Primary") is None
    finally:
        conn.close()


def test_find_card_nickname_none_matches_only_null_rows(db_path):
    conn = get_connection()
    try:
        named_id = create_card(conn, "FAKE BANK", "FAKE CARD TYPE", "Primary")
        unnamed_id = create_card(conn, "FAKE BANK", "FAKE CARD TYPE", None)

        found = find_card(conn, "FAKE BANK", "FAKE CARD TYPE", None)

        assert found["id"] == unnamed_id
        assert found["id"] != named_id
    finally:
        conn.close()


def test_list_cards_returns_all_ordered_by_created_at(db_path):
    conn = get_connection()
    try:
        id_one = create_card(conn, "FAKE BANK A", "FAKE CARD TYPE", "Primary")
        id_two = create_card(conn, "FAKE BANK B", "FAKE CARD TYPE", "Primary")

        cards = list_cards(conn)

        assert [c["id"] for c in cards] == [id_one, id_two]
    finally:
        conn.close()


def test_list_cards_empty_returns_empty_list(db_path):
    conn = get_connection()
    try:
        assert list_cards(conn) == []
    finally:
        conn.close()
