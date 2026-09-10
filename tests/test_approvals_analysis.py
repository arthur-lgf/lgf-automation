"""Bucket APPS rows into weekly/monthly approvals-analysis bar series."""
from datetime import date

import pytest

from app.services import approvals as approvals_service
from app.services import approvals_analysis as aa

# Friday. Last completed Sunday is 9/6/2026. Six weeks: WE 08.02 … WE 09.06.
TODAY = date(2026, 9, 11)
COLS = approvals_service.DEFAULT_COLS


def _row(*, approved: str, amount: str, client: str = "Co") -> list[str]:
    row = [""] * 12
    row[COLS["date_approved"]] = approved
    row[COLS["client"]] = client
    row[COLS["amount"]] = amount
    return row


def test_weekly_six_completed_weeks_sunday_labels():
    values = [
        _row(approved="8/2/2026", amount="$1,000.00"),   # Sun 8/2
        _row(approved="8/5/2026", amount="$2,000.00"),   # week ending 8/9
        _row(approved="9/3/2026", amount="$3,000.00"),   # week ending 9/6
        _row(approved="9/7/2026", amount="$9,999.00"),   # in-progress week — excluded
    ]
    series = aa.build_approvals_analysis_series(
        values, "weekly", today=TODAY, cols=COLS, weekly_weeks=6
    )
    labels = [label for label, _ in series]
    assert labels == [
        "WE 08.02", "WE 08.09", "WE 08.16", "WE 08.23", "WE 08.30", "WE 09.06",
    ]
    by = dict(series)
    assert by["WE 08.02"] == 1000.0
    assert by["WE 08.09"] == 2000.0
    assert by["WE 08.16"] == 0.0
    assert by["WE 09.06"] == 3000.0
    assert "WE 09.13" not in labels


def test_weekly_skips_blank_client_like_tables():
    values = [
        _row(approved="9/3/2026", amount="$1,000.00", client=""),
        _row(approved="9/3/2026", amount="$400.00", client="Acme"),
    ]
    series = aa.build_approvals_analysis_series(
        values, "weekly", today=TODAY, cols=COLS, weekly_weeks=6
    )
    assert dict(series)["WE 09.06"] == 400.0


def test_monthly_five_completed_plus_current_with_data():
    values = [
        _row(approved="4/10/2026", amount="$10.00"),
        _row(approved="5/10/2026", amount="$20.00"),
        _row(approved="6/10/2026", amount="$30.00"),
        _row(approved="7/10/2026", amount="$40.00"),
        _row(approved="8/10/2026", amount="$50.00"),
        _row(approved="9/5/2026", amount="$60.00"),
        _row(approved="3/10/2026", amount="$999.00"),  # older than 5 completed
    ]
    series = aa.build_approvals_analysis_series(
        values, "monthly", today=TODAY, cols=COLS, monthly_months=5
    )
    assert [label for label, _ in series] == [
        "Apr 2026", "May 2026", "Jun 2026", "Jul 2026", "Aug 2026", "Sep 2026",
    ]
    assert series[-1] == ("Sep 2026", 60.0)


def test_monthly_drops_current_month_when_zero():
    values = [
        _row(approved="4/10/2026", amount="$10.00"),
        _row(approved="5/10/2026", amount="$20.00"),
        _row(approved="6/10/2026", amount="$30.00"),
        _row(approved="7/10/2026", amount="$40.00"),
        _row(approved="8/10/2026", amount="$50.00"),
    ]
    series = aa.build_approvals_analysis_series(
        values, "monthly", today=TODAY, cols=COLS, monthly_months=5
    )
    assert [label for label, _ in series] == [
        "Apr 2026", "May 2026", "Jun 2026", "Jul 2026", "Aug 2026",
    ]


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


def test_weekly_totals_match_report_matrix_for_one_week():
    values = [
        _row(approved="9/1/2026", amount="$100.00"),
        _row(approved="9/6/2026", amount="$50.50"),
        _row(approved="9/1/2026", amount="$10.00", client=""),
    ]
    series = aa.build_approvals_analysis_series(
        values, "weekly", today=TODAY, cols=COLS, weekly_weeks=6
    )
    report = approvals_service.build_report_matrix(
        values, date(2026, 8, 31), date(2026, 9, 6), cols=COLS
    )
    assert dict(series)["WE 09.06"] == report.total
