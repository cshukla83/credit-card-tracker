"""The bank registry: everything bank-specific about importing a statement.

Moved here from scripts/import_statement.py in Session 97 so the web upload
path (main.py) and the CLI share one registry rather than two copies. The
CLI still imports it under its old `_BANKS` name.

Each entry is keyed by the bank name exactly as stored in `cards.bank`, and
carries:

  password_env_key  the .env variable holding that bank's statement password
                    (per bank, not per card type -- the Session 5/30
                    convention, unchanged)
  parse             the bank's dispatch package's parse(); card_type routing
                    happens inside it
  card_type         the one card type the bank's dispatch currently routes.
                    Session 97's bank identification reads the bank off page 1
                    of the PDF but cannot read the card product reliably (no
                    sample's page 1 names "Coral" or "Titan"), so detection
                    reports this value. When a bank gains a second card-type
                    parser, this stops being a single string and detection has
                    to learn to tell them apart -- deliberately not built
                    ahead of that.
  landmark          a regex, matched case-insensitively against page-1 text,
                    that identifies the bank. Checked against every local
                    sample statement in Session 97: each matches exactly one
                    bank's landmark and none of the other three.
"""

from __future__ import annotations

from typing import Callable, NamedTuple

import parsers.hdfc as hdfc_dispatch
import parsers.icici as icici_dispatch
import parsers.indusind as indusind_dispatch
import parsers.sbi as sbi_dispatch


class Bank(NamedTuple):
    password_env_key: str
    parse: Callable[..., dict]
    card_type: str
    landmark: str


BANKS = {
    "HDFC": Bank(
        password_env_key="HDFC_SAMPLE_PASSWORD",
        parse=hdfc_dispatch.parse,
        card_type="Diners",
        landmark=r"HDFC Bank Credit Card",
    ),
    "ICICI": Bank(
        password_env_key="ICICI_SAMPLE_PASSWORD",
        parse=icici_dispatch.parse,
        card_type="Coral",
        landmark=r"ICICI Bank Credit Card",
    ),
    "SBI": Bank(
        password_env_key="SBI_SAMPLE_PASSWORD",
        parse=sbi_dispatch.parse,
        card_type="Titan",
        landmark=r"\bSBI Card\b",
    ),
    "IndusInd": Bank(
        password_env_key="INDUSIND_SAMPLE_PASSWORD",
        parse=indusind_dispatch.parse,
        card_type="Legend",
        landmark=r"IndusInd Bank",
    ),
}
