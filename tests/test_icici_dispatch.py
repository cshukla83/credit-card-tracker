import pytest

import parsers.icici as icici_dispatch
from parsers import icici_coral

# Fabricated fixture -- dispatch routing is tested against a stubbed-out
# icici_coral.parse(), never a real PDF or real transaction data.
_FAKE_PARSED_STATEMENT = {
    "period_start": "2026-01-01",
    "period_end": "2026-01-31",
    "transactions": [
        {
            "date": "2026-01-01",
            "description": "FAKE MERCHANT",
            "amount": 100.0,
            "type": "debit",
            "reward_points": 0,
        }
    ],
}


def test_parse_coral_routes_to_icici_coral(monkeypatch):
    calls = []

    def fake_parse(pdf_path, password):
        calls.append((pdf_path, password))
        return _FAKE_PARSED_STATEMENT

    monkeypatch.setattr(icici_coral, "parse", fake_parse)

    result = icici_dispatch.parse("fake.pdf", "fake-password", card_type="Coral")

    assert result == _FAKE_PARSED_STATEMENT
    assert calls == [("fake.pdf", "fake-password")]


@pytest.mark.parametrize("card_type", ["coral", "CORAL", "Coral", " Coral "])
def test_parse_coral_case_insensitive(monkeypatch, card_type):
    monkeypatch.setattr(icici_coral, "parse", lambda pdf_path, password: _FAKE_PARSED_STATEMENT)

    result = icici_dispatch.parse("fake.pdf", "fake-password", card_type=card_type)

    assert result == _FAKE_PARSED_STATEMENT


def test_parse_unknown_card_type_raises_not_implemented():
    with pytest.raises(NotImplementedError, match="Amazon Pay"):
        icici_dispatch.parse("fake.pdf", "fake-password", card_type="Amazon Pay")
