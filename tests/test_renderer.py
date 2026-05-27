import json
from pathlib import Path

import pytest

from app.services.renderer import ThemeNotFoundError, classify_rows, render

FIXTURE = Path(__file__).parent / "fixtures" / "sample_values.json"


def _values() -> list[list[str]]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_classify_rows_kinds_in_order():
    rows = classify_rows(_values())
    kinds = [r["kind"] for r in rows]
    assert kinds == [
        "title",
        "header",
        "data",
        "data",
        "data",
        "spacer",
        "totals",
        "totals",
        "totals",
    ]


def test_classify_rows_pads_to_width():
    rows = classify_rows(_values())
    widths = {len(r["cells"]) for r in rows}
    assert widths == {4}
    assert all(r["width"] == 4 for r in rows)


def test_classify_rows_marks_amounts_in_data():
    rows = classify_rows(_values())
    first_data = next(r for r in rows if r["kind"] == "data")
    assert first_data["cells"][0] == {"value": "1", "is_amount": True}
    assert first_data["cells"][1] == {"value": "Mike", "is_amount": False}
    assert first_data["cells"][3] == {"value": "$995.00", "is_amount": True}


def test_classify_rows_totals_detects_average_and_total():
    rows = classify_rows(_values())
    totals = [r for r in rows if r["kind"] == "totals"]
    assert len(totals) == 3
    assert totals[0]["cells"][0]["value"] == "Total # of sales:"
    assert totals[2]["cells"][0]["value"] == "Average sale:"
    assert totals[1]["cells"][3] == {"value": "$2,085.00", "is_amount": True}


def test_classify_rows_handles_ragged_input():
    rows = classify_rows([["a", "b", "c"], ["x"], []])
    assert [r["kind"] for r in rows] == ["header", "data", "spacer"]
    assert [c["value"] for c in rows[1]["cells"]] == ["x", "", ""]


def test_classify_rows_only_ranked_drops_non_numeric_data_rows():
    values = [
        ["DAILY SALES REPORT"],
        ["Rank", "Rep", "Qty", "Amount"],
        ["1", "Mike", "1", "$995.00"],
        ["2", "Eric", "1", "$695.00"],
        ["3", "Joab", "1", "$395.00"],
        [],
        ["", "Jeffrey", "0", "$0.00"],
        ["", "Dan", "0", "$0.00"],
        ["", "Chris", "0", "$0.00"],
        [],
        ["Total # of sales:", "", "", "3"],
        ["Total amount:", "", "", "$2,085.00"],
        ["Average sale:", "", "", "$695.00"],
    ]
    rows = classify_rows(values, only_ranked=True)
    kinds = [r["kind"] for r in rows]
    assert kinds == [
        "title",
        "header",
        "data",
        "data",
        "data",
        "spacer",
        "totals",
        "totals",
        "totals",
    ]
    data_rows = [r for r in rows if r["kind"] == "data"]
    assert [r["cells"][0]["value"] for r in data_rows] == ["1", "2", "3"]


def test_classify_rows_only_ranked_collapses_consecutive_spacers():
    values = [
        ["1", "Mike", "1", "$995.00"],
        [],
        [],
        ["", "Jeffrey", "0", "$0.00"],
        [],
        [],
        ["Total:", "", "", "1"],
    ]
    rows = classify_rows(values, only_ranked=True)
    # Jeffrey row dropped; the two pre- and post- spacers each collapse to one.
    kinds = [r["kind"] for r in rows]
    assert kinds == ["data", "spacer", "totals"]


def test_render_default_theme_is_dark_green_and_inlines_css():
    html = render(_values(), title="Daily Sales")  # no theme arg -> default
    assert "<title>Daily Sales</title>" in html
    assert 'id="report-table"' in html
    assert 'class="title-row"' in html
    assert 'class="header-row"' in html
    assert 'class="totals-row"' in html
    assert 'class="data-row"' in html
    assert 'class="spacer-row"' in html
    # dark_green theme tokens
    assert "#4ade80" in html  # bright green header text
    assert "#fbbf24" in html  # yellow title / totals text
    assert "#103a2c" in html  # data row green background
    # Cell content
    assert "DAILY SALES REPORT" in html
    assert ">$995.00<" in html
    assert 'class="amount"' in html


def test_render_dark_gold_theme_still_available():
    html = render(_values(), theme="dark_gold")
    assert "#b91c1c" in html  # red title bar
    assert "#fef3c7" in html  # cream totals bar


def test_render_unknown_theme_raises():
    with pytest.raises(ThemeNotFoundError):
        render(_values(), theme="does_not_exist")
