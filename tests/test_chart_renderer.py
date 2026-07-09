"""Render a bar-chart series to a self-contained HTML page with inline SVG.

The page wraps everything in ``<div id="chart">`` (the screenshot selector) and
draws one ``<rect class="bar">`` per data point with a value label above and a
category label below. No external resources — inline SVG only — so Playwright's
``set_content(wait_until="networkidle")`` is reliable."""
from app.services import chart_renderer as cr

SERIES = [
    ("WE 06.13", 62919.0),
    ("WE 07.04", 60319.0),
    ("WE 07.11", 23379.0),
]


def test_wraps_in_chart_selector_and_title():
    html = cr.render_bar_chart(SERIES, title="Weekly Sales Analysis")
    assert 'id="chart"' in html
    assert "WEEKLY SALES ANALYSIS" in html  # title rendered uppercase
    assert "<svg" in html


def test_one_bar_per_series_point():
    html = cr.render_bar_chart(SERIES, title="Weekly Sales Analysis")
    assert html.count('class="bar"') == len(SERIES)


def test_value_and_category_labels_present():
    html = cr.render_bar_chart(SERIES, title="Weekly Sales Analysis")
    for label, amount in SERIES:
        assert label in html
        assert cr._format_money(amount) in html  # e.g. "$62,919"


def test_empty_series_does_not_crash():
    html = cr.render_bar_chart([], title="Weekly Sales Analysis")
    assert 'id="chart"' in html
    assert html.count('class="bar"') == 0


def test_nice_ceiling_covers_max_with_round_step():
    nmax, step = cr._nice_ceiling(62919.0)
    assert nmax >= 62919.0
    # nmax is a whole number of steps and the step is a 1/2/2.5/5 * 10^n figure
    assert abs((nmax / step) - round(nmax / step)) < 1e-9
    assert cr._nice_ceiling(0.0)[0] > 0  # degenerate all-zero series is safe


def test_html_escapes_category_labels():
    html = cr.render_bar_chart([("A & B <x>", 10.0)], title="t")
    assert "A &amp; B &lt;x&gt;" in html
    assert "<x>" not in html
