"""Bucket Apptrack Raw rows into a weekly/monthly bar-chart series.

Mirrors the APPROVALS ANALYSIS tab SUMPRODUCT on the KPI workbook:

  =SUMPRODUCT(
    IFERROR(VALUE('Apptrack Raw'!$H$2:$H),0)*
    (INT('Apptrack Raw'!$B$2:$B)>=start)*
    (INT('Apptrack Raw'!$B$2:$B)<=end)
  )

B = Date Approved, H = Amount Approved For. No status or client filter.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from app.services.approvals import _cell, parse_amount, parse_date

_MONTH_ABBR = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)

# 0-based indices within an A:H fetch of Apptrack Raw.
APPTRACK_RAW_COLS: dict[str, int] = {
    "date_approved": 1,  # B
    "amount": 7,         # H Amount Approved For
}


def _sunday_of(day: date) -> date:
    return day + timedelta(days=(6 - day.weekday()))


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    idx = year * 12 + (month - 1) + delta
    return idx // 12, idx % 12 + 1


def _iter_deals(values: list[list[str]], cols: dict[str, int]):
    for row in values:
        approved = parse_date(_cell(row, cols["date_approved"]))
        if approved is None:
            continue
        yield approved, parse_amount(_cell(row, cols["amount"]))


def _all_zero(series: list[tuple[str, float]]) -> bool:
    return not series or all(amount == 0.0 for _, amount in series)


def build_approvals_analysis_series(
    values: list[list[str]],
    kind: str,
    *,
    today: date,
    cols: Optional[dict[str, int]] = None,
    weekly_weeks: int = 6,
    monthly_months: int = 6,
) -> list[tuple[str, float]]:
    """Return ``[(label, amount), …]`` oldest-first.

    ``kind`` is ``"weekly"`` or ``"monthly"``. All-zero series returns ``[]``
    so the CLI skips posting.
    """
    if kind not in ("weekly", "monthly"):
        raise ValueError(f"kind must be 'weekly' or 'monthly'; got {kind!r}")
    cols = cols or APPTRACK_RAW_COLS
    if kind == "weekly":
        series = _weekly_series(values, today, cols, weekly_weeks)
    else:
        series = _monthly_series(values, today, cols, monthly_months)
    return [] if _all_zero(series) else series


def _weekly_series(
    values: list[list[str]], today: date, cols: dict[str, int], n: int
) -> list[tuple[str, float]]:
    if n <= 0:
        return []
    last_sunday = _sunday_of(today)
    sundays = [last_sunday - timedelta(days=7 * i) for i in range(n - 1, -1, -1)]
    totals = {sunday: 0.0 for sunday in sundays}
    lo, hi = sundays[0] - timedelta(days=6), sundays[-1]
    for approved, amount in _iter_deals(values, cols):
        if approved < lo or approved > hi:
            continue
        sunday = _sunday_of(approved)
        if sunday in totals:
            totals[sunday] += amount
    return [
        (f"WE {sunday.month:02d}.{sunday.day:02d}", totals[sunday])
        for sunday in sundays
    ]


def _monthly_series(
    values: list[list[str]], today: date, cols: dict[str, int], n: int
) -> list[tuple[str, float]]:
    if n <= 0:
        return []
    months = [_shift_month(today.year, today.month, -i) for i in range(n - 1, -1, -1)]
    totals = {key: 0.0 for key in months}
    for approved, amount in _iter_deals(values, cols):
        key = (approved.year, approved.month)
        if key in totals:
            totals[key] += amount
    return [
        (f"{_MONTH_ABBR[month - 1]} {year}", totals[(year, month)])
        for year, month in months
    ]
