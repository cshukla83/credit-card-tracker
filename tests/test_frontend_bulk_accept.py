"""Bulk-accept eligibility for subcategory suggestions, run against the real
frontend code (Session 88).

The project has no frontend test suite (Session 79's convention). This file
does not invent one: it lifts the three functions that decide subcategory
bulk-accept eligibility out of static/index.html verbatim, runs them under
the JavaScriptCore shell that ships with macOS (`jsc`), and asserts on the
pairs they produce. If `jsc` is not present the tests skip rather than fail,
so the suite stays green elsewhere.

What this pins down (the Session 88 item-2 question): eligibility is
"exclude same_as_category by name", not an allowlist of tiers -- so the
merchant_category tier is bulk-acceptable without being named anywhere in
the frontend, and so is any future learned tier.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

INDEX = Path(__file__).resolve().parent.parent / "static" / "index.html"
JSC = shutil.which("jsc") or (
    "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"
)
FUNCTIONS = ("hasSubcategory", "subSuggestionFor", "acceptSubcategoryPairs", "precedentText")

pytestmark = pytest.mark.skipif(not Path(JSC).exists(), reason="jsc (JavaScriptCore shell) not available")


def _lift(name: str) -> str:
    """The source of top-level-in-script `function name(...) {...}` from index.html."""
    source = INDEX.read_text()
    match = re.search(rf"\n    function {name}\(.*?\n    \}}\n", source, re.DOTALL)
    assert match, f"function {name} not found in index.html"
    return match.group(0)


def _run(txns, suggestions):
    """acceptSubcategoryPairs(txns) with review.suggestions stubbed from
    {id: subcategory-suggestion-or-None}; returns the pairs list."""
    script = "".join(_lift(n) for n in FUNCTIONS) + f"""
    const review = {{ suggestions: new Map() }};
    for (const [id, sub] of Object.entries({json.dumps(suggestions)})) {{
      review.suggestions.set(Number(id), {{ subcategory: sub }});
    }}
    print(JSON.stringify(acceptSubcategoryPairs({json.dumps(txns)})));
    """
    return json.loads(_js(script))


def _js(script: str) -> str:
    result = subprocess.run([JSC, "-e", script], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _txn(i, subcategory=None):
    return {"id": i, "subcategory": subcategory}


def _sugg(match_type, value="Household", confidence=1.0, **extra):
    return {"value": value, "confidence": confidence, "match_type": match_type, **extra}


def test_eligibility_is_exclude_fallback_by_name_not_an_allowlist():
    src = _lift("acceptSubcategoryPairs")
    assert '!== "same_as_category"' in src
    assert '"exact"' not in src and '"merchant_category"' not in src


def test_all_merchant_category_selection_is_fully_eligible():
    txns = [_txn(1), _txn(2), _txn(3)]
    suggestions = {
        1: _sugg("merchant_category", "Household", 1.0, precedents=4),
        2: _sugg("merchant_category", "Snacks", 0.6, precedents=5),
        3: _sugg("merchant_category", "Household", 0.5, precedents=2),
    }
    assert _run(txns, suggestions) == [
        {"transaction_id": 1, "subcategory": "Household"},
        {"transaction_id": 2, "subcategory": "Snacks"},
        {"transaction_id": 3, "subcategory": "Household"},
    ]


def test_all_same_as_category_selection_stays_ineligible():
    txns = [_txn(1), _txn(2)]
    suggestions = {1: _sugg("same_as_category", "Grocery"), 2: _sugg("same_as_category", "Food")}
    assert _run(txns, suggestions) == []


def test_mixed_selection_counts_only_learned_tiers_and_skips_labelled_rows():
    txns = [_txn(1), _txn(2), _txn(3), _txn(4, "Already"), _txn(5)]
    suggestions = {
        1: _sugg("exact", "Cafe"),
        2: _sugg("same_as_category", "Food"),
        3: _sugg("merchant_category", "Household", 1.0, precedents=1),
        4: _sugg("merchant_category", "Ignored", 1.0, precedents=1),  # row already has one
        # 5: no suggestion entry at all
    }
    assert _run(txns, suggestions) == [
        {"transaction_id": 1, "subcategory": "Cafe"},
        {"transaction_id": 3, "subcategory": "Household"},
    ]


def test_precedent_badge_text_shows_agreeing_count_share_and_percent():
    script = _lift("precedentText") + """
    print(JSON.stringify([
      precedentText({confidence: 1.0, precedents: 1}),
      precedentText({confidence: 0.75, precedents: 4}),
      precedentText({confidence: 0.6, precedents: 5}),
    ]));
    """
    assert json.loads(_js(script)) == [
        "precedent 1/1 · 100%",
        "precedent 3/4 · 75%",
        "precedent 3/5 · 60%",
    ]
