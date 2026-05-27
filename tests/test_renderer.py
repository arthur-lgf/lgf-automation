import json
from pathlib import Path

import pytest

from app.services.renderer import ThemeNotFoundError, normalize_rows, render

FIXTURE = Path(__file__).parent / "fixtures" / "sample_values.json"


def _values() -> list[list[str]]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_normalize_rows_classifies_amounts():
    header, body = normalize_rows(_values())
    assert header == ["Region", "Rep", "Deals", "Revenue", "Margin"]
    assert len(body) == 4
    first_row = body[0]
    assert first_row[0] == {"value": "West", "is_amount": False}
    assert first_row[2] == {"value": "12", "is_amount": True}
    assert first_row[3] == {"value": "$48,200", "is_amount": True}
    assert first_row[4] == {"value": "32%", "is_amount": True}
    assert first_row[1] == {"value": "A. Lopez", "is_amount": False}


def test_normalize_rows_pads_ragged_rows():
    header, body = normalize_rows([["a", "b", "c"], ["x"], ["y", "z"]])
    assert header == ["a", "b", "c"]
    assert [c["value"] for c in body[0]] == ["x", "", ""]
    assert [c["value"] for c in body[1]] == ["y", "z", ""]


def test_render_includes_theme_css_and_table():
    html = render(_values(), theme="dark_gold", title="Q1 Report")
    assert "<title>Q1 Report</title>" in html
    assert 'id="report-table"' in html
    assert "#f5b50a" in html  # gold from dark_gold.css
    assert ">$48,200<" in html
    assert 'class="amount"' in html


def test_render_unknown_theme_raises():
    with pytest.raises(ThemeNotFoundError):
        render(_values(), theme="does_not_exist")
