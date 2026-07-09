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
