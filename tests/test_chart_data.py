"""Extract weekly/monthly bar-chart series from the Analysis-tab matrix.

The tab (gid 1867438179) holds two side-by-side blocks: weekly in cols B:E
(Start | End | WE label | SALES) and monthly in cols N:Q (Start | End | MONTH |
SALES). Future periods carry $0.00; we drop any period whose Start Date is after
'today' so partial current periods stay but placeholders don't."""
from datetime import date

import pytest

from app.services import chart_data as cd

TODAY = date(2026, 7, 9)


def _row(pairs: dict) -> list:
    """Build a ragged row with values placed at given 0-based column indices."""
    width = max(pairs) + 1 if pairs else 0
    row = [""] * width
    for idx, val in pairs.items():
        row[idx] = val
    return row


def _sheet() -> list[list[str]]:
    return [
        [""],
        # weekly header (B:E) + block title in G; monthly header (N:Q) too
        _row({1: "Start Date", 2: "End Date", 3: "WE", 4: "SALES",
              6: "WEEKLY SALES ANALYSIS",
              13: "Start Date", 14: "End Date", 15: "MONTH", 16: "SALES"}),
        _row({1: "5/31/2026", 2: "6/6/2026", 3: "WE 06.13", 4: "$62,919.00",
              13: "6/1/2026", 14: "6/30/2026", 15: "Jun 2026", 16: "$223,054.00"}),
        _row({1: "6/28/2026", 2: "7/4/2026", 3: "WE 07.04", 4: "$60,319.00",
              13: "7/1/2026", 14: "7/31/2026", 15: "Jul 2026", 16: "$55,363.00"}),
        _row({1: "7/5/2026", 2: "7/11/2026", 3: "WE 07.11", 4: "$23,379.00",
              13: "8/1/2026", 14: "8/31/2026", 15: "Aug 2026", 16: "$0.00"}),
        # future week — excluded
        _row({1: "7/12/2026", 2: "7/18/2026", 3: "WE 07.18", 4: "$0.00"}),
    ]


def test_weekly_series_extracts_label_and_amount():
    series = cd.build_analysis_series(_sheet(), "weekly", today=TODAY)
    assert series == [
        ("WE 06.13", 62919.0),
        ("WE 07.04", 60319.0),
        ("WE 07.11", 23379.0),
    ]


def test_monthly_series_extracts_label_and_amount():
    series = cd.build_analysis_series(_sheet(), "monthly", today=TODAY)
    assert series == [("Jun 2026", 223054.0), ("Jul 2026", 55363.0)]


def test_future_periods_are_dropped():
    weekly = cd.build_analysis_series(_sheet(), "weekly", today=TODAY)
    monthly = cd.build_analysis_series(_sheet(), "monthly", today=TODAY)
    assert "WE 07.18" not in [label for label, _ in weekly]  # start 7/12 > today
    assert "Aug 2026" not in [label for label, _ in monthly]  # start 8/1 > today


def test_header_and_blank_rows_are_skipped():
    # Only real data rows survive (header 'Start Date' has no parseable date).
    series = cd.build_analysis_series(_sheet(), "weekly", today=TODAY)
    assert all(label.startswith("WE ") for label, _ in series)


def test_empty_input_returns_empty_series():
    assert cd.build_analysis_series([], "weekly", today=TODAY) == []
    assert cd.build_analysis_series([[""], [""]], "monthly", today=TODAY) == []


def test_invalid_kind_raises():
    with pytest.raises(ValueError):
        cd.build_analysis_series(_sheet(), "quarterly", today=TODAY)


# --- schedule gates -----------------------------------------------------------


def test_gate_none_always_allows():
    assert cd.gate_allows("none", date(2026, 7, 15)) is True
    assert cd.gate_allows("", date(2026, 7, 15)) is True


def test_gate_first_monday():
    assert cd.gate_allows("first-monday", date(2026, 7, 6)) is True   # Mon, day 6
    assert cd.gate_allows("first-monday", date(2026, 7, 13)) is False  # Mon, day 13
    assert cd.gate_allows("first-monday", date(2026, 7, 7)) is False   # Tue


def test_gate_last_day():
    assert cd.gate_allows("last-day", date(2026, 7, 31)) is True
    assert cd.gate_allows("last-day", date(2026, 7, 30)) is False
    assert cd.gate_allows("last-day", date(2026, 2, 28)) is True  # 2026 not a leap year


def test_gate_invalid_raises():
    with pytest.raises(ValueError):
        cd.gate_allows("weekly", date(2026, 7, 1))


# --- current-month total from the Sales Report tab ----------------------------


def _sales_report() -> list[list[str]]:
    # gid 170384010 monthly block (cols G:J after a G1:J50 fetch = Rank/Name/Qty/Amount).
    # A ranked block on top, then an unranked duplicate block that must be ignored.
    return [
        ["MONTHLY SALES REPORT"],
        ["JULY 2026"],
        ["Rank", "Name", "Qty", "Amount"],
        ["1", "Dan", "8", "$13,524.00"],
        ["2", "Eric", "11", "$12,657.00"],
        ["3", "Joab", "10", "$11,697.00"],
        ["", "", "", ""],
        ["", "Dan", "8", "$13,524.00"],   # unranked duplicate — must NOT be summed
        ["", "Eric", "11", "$12,657.00"],
    ]


def test_sum_ranked_amounts_sums_only_ranked_rows():
    total, count = cd.sum_ranked_amounts(_sales_report())
    assert count == 3
    assert total == 13524.0 + 12657.0 + 11697.0  # 37878.0


def test_sum_ranked_amounts_empty_when_no_ranked_rows():
    assert cd.sum_ranked_amounts([["Rank", "Name", "Qty", "Amount"]]) == (0.0, 0)


def test_monthly_series_overrides_current_month_value():
    series = cd.build_analysis_series(
        _sheet(), "monthly", today=TODAY, current_month_total=83485.0
    )
    by_label = dict(series)
    assert by_label["Jul 2026"] == 83485.0   # current month replaced (TODAY is July)
    assert by_label["Jun 2026"] == 223054.0  # prior month untouched


def test_current_month_override_ignored_for_weekly():
    series = cd.build_analysis_series(
        _sheet(), "weekly", today=TODAY, current_month_total=999.0
    )
    assert ("WE 07.11", 23379.0) in series  # weekly unaffected by the override


# --- limit (weekly: only the most recent N weeks) -----------------------------


def _weekly_rows(n: int) -> list[list[str]]:
    """n weekly rows with chronological start dates all <= TODAY."""
    from datetime import timedelta

    rows = [_row({1: "Start Date", 2: "End Date", 3: "WE", 4: "SALES"})]
    base = date(2026, 5, 4)  # well before TODAY (2026-07-09)
    for i in range(n):
        start = base + timedelta(days=7 * i)
        rows.append(_row({
            1: f"{start.month}/{start.day}/{start.year}",
            3: f"WE {start.month:02d}.{start.day:02d}",
            4: f"${1000 * (i + 1)}.00",
        }))
    return rows


def test_limit_keeps_only_most_recent_weeks():
    rows = _weekly_rows(8)
    limited = cd.build_analysis_series(rows, "weekly", today=TODAY, limit=5)
    full = cd.build_analysis_series(rows, "weekly", today=TODAY)
    assert len(limited) == 5
    assert limited == full[-5:]  # the 5 most recent, in order


def test_limit_none_returns_all():
    rows = _weekly_rows(8)
    assert len(cd.build_analysis_series(rows, "weekly", today=TODAY, limit=None)) == 8


def test_limit_larger_than_series_returns_all():
    rows = _weekly_rows(3)
    assert len(cd.build_analysis_series(rows, "weekly", today=TODAY, limit=5)) == 3
