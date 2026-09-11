"""Bucket Apptrack Raw rows with the APPROVALS ANALYSIS SUMPRODUCT.

Sum H Amount Approved For where B Date Approved is in the period.
No status or client filter — same as the KPI tab formula.
"""
from datetime import date

import pytest

from app.services import approvals_analysis as aa

# Friday. Sheet weekly graph is the current week plus the 5 before it:
# WE 08.09 … WE 09.13 (in progress). WE 08.02 and future WE 09.20 are off.
TODAY = date(2026, 9, 11)
COLS = aa.APPTRACK_RAW_COLS


def _row(*, approved: str, amount: str) -> list[str]:
    row = [""] * 8
    row[COLS["date_approved"]] = approved
    row[COLS["amount"]] = amount
    return row


def test_weekly_matches_sheet_graph_including_in_progress_week():
    values = [
        _row(approved="8/2/2026", amount="$941,900.00"),   # WE 08.02 — off the 6
        _row(approved="8/5/2026", amount="$928,400.00"),   # WE 08.09
        _row(approved="9/3/2026", amount="$1,155,500.00"),  # WE 09.06
        _row(approved="9/7/2026", amount="$874,100.00"),   # WE 09.13 in progress
        _row(approved="9/14/2026", amount="$1.00"),         # future — excluded
    ]
    series = aa.build_approvals_analysis_series(
        values, "weekly", today=TODAY, cols=COLS, weekly_weeks=6
    )
    labels = [label for label, _ in series]
    assert labels == [
        "WE 08.09", "WE 08.16", "WE 08.23", "WE 08.30", "WE 09.06", "WE 09.13",
    ]
    by = dict(series)
    assert by["WE 08.09"] == 928400.0
    assert by["WE 09.06"] == 1155500.0
    assert by["WE 09.13"] == 874100.0
    assert "WE 08.02" not in labels
    assert "WE 09.20" not in labels


def test_weekly_sumproduct_includes_every_row_with_date_approved():
    """KPI formula has no status/client filter — denied and blank client count."""
    values = [
        _row(approved="8/3/2026", amount="$800,000.00"),
        _row(approved="8/9/2026", amount="$141,900.00"),
        _row(approved="8/2/2026", amount="$999,999.00"),  # prior week, off the 6
    ]
    series = aa.build_approvals_analysis_series(
        values, "weekly", today=TODAY, cols=COLS, weekly_weeks=6
    )
    assert dict(series)["WE 08.09"] == 941900.0


def test_weekly_counts_rows_regardless_of_status():
    """SUMPRODUCT does not filter Status — a denied $5,000 still counts."""
    row = [""] * 8
    row[COLS["date_approved"]] = "8/5/2026"
    row[3] = "Denied from that card"
    row[COLS["amount"]] = "$5,000.00"
    series = aa.build_approvals_analysis_series(
        [row], "weekly", today=TODAY, cols=COLS, weekly_weeks=6
    )
    assert dict(series)["WE 08.09"] == 5000.0


def test_monthly_matches_sheet_graph_including_current_month():
    values = [
        _row(approved="3/10/2026", amount="$999.00"),  # Mar — off the 6
        _row(approved="4/10/2026", amount="$10.00"),
        _row(approved="5/10/2026", amount="$20.00"),
        _row(approved="6/10/2026", amount="$30.00"),
        _row(approved="7/10/2026", amount="$40.00"),
        _row(approved="8/10/2026", amount="$50.00"),
        _row(approved="9/5/2026", amount="$60.00"),
        _row(approved="10/1/2026", amount="$1.00"),  # future — excluded
    ]
    series = aa.build_approvals_analysis_series(
        values, "monthly", today=TODAY, cols=COLS, monthly_months=6
    )
    assert [label for label, _ in series] == [
        "Apr 2026", "May 2026", "Jun 2026", "Jul 2026", "Aug 2026", "Sep 2026",
    ]
    assert series[-1] == ("Sep 2026", 60.0)
    assert "Mar 2026" not in [label for label, _ in series]


def test_monthly_keeps_current_month_bar_when_zero():
    values = [
        _row(approved="4/10/2026", amount="$10.00"),
        _row(approved="5/10/2026", amount="$20.00"),
        _row(approved="6/10/2026", amount="$30.00"),
        _row(approved="7/10/2026", amount="$40.00"),
        _row(approved="8/10/2026", amount="$50.00"),
    ]
    series = aa.build_approvals_analysis_series(
        values, "monthly", today=TODAY, cols=COLS, monthly_months=6
    )
    assert [label for label, _ in series] == [
        "Apr 2026", "May 2026", "Jun 2026", "Jul 2026", "Aug 2026", "Sep 2026",
    ]
    assert series[-1] == ("Sep 2026", 0.0)


def test_all_zero_series_returns_empty():
    assert aa.build_approvals_analysis_series(
        [], "weekly", today=TODAY, cols=COLS, weekly_weeks=6
    ) == []
    assert aa.build_approvals_analysis_series(
        [_row(approved="1/1/2020", amount="$1.00")],
        "weekly", today=TODAY, cols=COLS, weekly_weeks=6,
    ) == []


def test_invalid_kind_raises():
    with pytest.raises(ValueError):
        aa.build_approvals_analysis_series([], "quarterly", today=TODAY, cols=COLS)
