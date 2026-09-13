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

Session 90 reuses the same harness for the inline editor's pure
arrow-key step function, `stepHighlight`; the DOM-bound parts of that
feature (class toggling, Enter dispatch) stay on the manual-verification
list.
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


# --- inline editor: arrow-key highlight step (Session 90) ---------------------


def _steps(cases):
    """stepHighlight(current, key, count) for each (current, key, count)."""
    script = _lift("stepHighlight") + f"""
    print(JSON.stringify({json.dumps(cases)}.map(([c, k, n]) => stepHighlight(c, k, n))));
    """
    return json.loads(_js(script))


def test_step_highlight_first_press_lands_on_first_or_last():
    assert _steps([[-1, "ArrowDown", 3], [-1, "ArrowUp", 3]]) == [0, 2]


def test_step_highlight_moves_one_and_stops_at_the_ends_without_wrapping():
    assert _steps([
        [0, "ArrowDown", 3], [1, "ArrowDown", 3], [2, "ArrowDown", 3],  # 0->1->2, stays 2
        [2, "ArrowUp", 3], [1, "ArrowUp", 3], [0, "ArrowUp", 3],        # 2->1->0, stays 0
    ]) == [1, 2, 2, 1, 0, 0]


def test_step_highlight_empty_menu_and_other_keys():
    assert _steps([
        [-1, "ArrowDown", 0], [-1, "ArrowUp", 0], [1, "ArrowDown", 0],  # nothing to land on
        [1, "Enter", 3], [-1, "a", 3],                                    # not an arrow: unchanged
    ]) == [-1, -1, -1, 1, -1]


# --- subcategory gating and bulk skip (Session 92) ----------------------------

GATE_FUNCTIONS = ("isOpen", "canEditSubcategory", "partitionSubcategoryTargets", "skipSummary")


def _gate(expr):
    script = "".join(_lift(n) for n in GATE_FUNCTIONS) + f"\nprint(JSON.stringify({expr}));\n"
    return json.loads(_js(script))


def test_can_edit_subcategory_follows_category_presence():
    assert _gate('[{category: null}, {category: undefined}, {}, {category: "Food"}, {category: ""}]'
                 '.map(canEditSubcategory)') == [False, False, False, True, True]


def test_bulk_partition_mixed_selection_and_summary():
    txns = '[{id: 1, category: "Food"}, {id: 2, category: null}, {id: 3, category: "Food"}, '\
           '{id: 4, category: null}, {id: 5, category: "Travel"}, {id: 6, category: "Food"}, {id: 7, category: null}]'
    assert _gate(f"partitionSubcategoryTargets({txns})") == {"eligible": [1, 3, 5, 6], "skipped": [2, 4, 7]}
    assert _gate("skipSummary(4, 3)") == "Updated subcategory for 4 of 7 selected rows \u2014 3 skipped (no category set)"


def test_bulk_partition_all_category_set_is_unchanged_behaviour():
    # Regression: every row eligible, nothing skipped, and no notice at all
    # -- assign() is then called exactly as it was before Session 92.
    txns = '[{id: 1, category: "Food"}, {id: 2, category: "Travel"}, {id: 3, category: "Food"}]'
    assert _gate(f"partitionSubcategoryTargets({txns})") == {"eligible": [1, 2, 3], "skipped": []}
    assert _gate("skipSummary(3, 0)") == ""


def test_gate_lifts_as_soon_as_the_row_object_carries_a_category():
    # The predicate is evaluated per render from the row object; once the
    # reload after a category write carries the value, the pencil is built
    # enabled. This pins the predicate half; the rebuild itself is DOM.
    assert _gate('(() => { const t = {id: 1, category: null}; const before = canEditSubcategory(t); '
                 't.category = "Food"; return [before, canEditSubcategory(t)]; })()') == [False, True]


def test_category_less_row_has_no_subcategory_suggestion_to_ghost():
    # The engine returns null for a row without a category (Session 43);
    # subSuggestionFor passes that through as null, so the gated cell can
    # only ever be the dash, never a ghost value.
    script = _lift("hasSubcategory") + _lift("subSuggestionFor") + """
    const review = { suggestions: new Map([[1, { subcategory: null }], [2, {}]]) };
    print(JSON.stringify([subSuggestionFor({id: 1, subcategory: null}), subSuggestionFor({id: 2, subcategory: null}),
                          subSuggestionFor({id: 3, subcategory: null})]));
    """
    assert json.loads(_js(script)) == [None, None, None]
