import pytest

import parsers.hdfc as hdfc_dispatch
from parsers import hdfc_diners

# Fabricated fixture -- dispatch routing is tested against a stubbed-out
# hdfc_diners.parse(), never a real PDF or real transaction data.
_FAKE_PARSED_STATEMENT = {
    "period_start": "2026-01-01",
    "period_end": "2026-01-31",
    "transactions": [
        {
            "date": "2026-01-01",
            "description": "FAKE MERCHANT",
            "amount": 100.0,
            "type": "debit",
            "reward_points": None,
        }
    ],
}


def test_parse_diners_routes_to_hdfc_diners(monkeypatch):
    calls = []

    def fake_parse(pdf_path, password):
        calls.append((pdf_path, password))
        return _FAKE_PARSED_STATEMENT

    monkeypatch.setattr(hdfc_diners, "parse", fake_parse)

    result = hdfc_dispatch.parse("fake.pdf", "fake-password", card_type="Diners")

    assert result == _FAKE_PARSED_STATEMENT
    assert calls == [("fake.pdf", "fake-password")]


@pytest.mark.parametrize("card_type", ["diners", "DINERS", "Diners", " Diners "])
def test_parse_diners_case_insensitive(monkeypatch, card_type):
    monkeypatch.setattr(hdfc_diners, "parse", lambda pdf_path, password: _FAKE_PARSED_STATEMENT)

    result = hdfc_dispatch.parse("fake.pdf", "fake-password", card_type=card_type)

    assert result == _FAKE_PARSED_STATEMENT


def test_parse_unknown_card_type_raises_not_implemented():
    with pytest.raises(NotImplementedError, match="Regalia"):
        hdfc_dispatch.parse("fake.pdf", "fake-password", card_type="Regalia")
