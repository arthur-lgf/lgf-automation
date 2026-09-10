"""Bucket APPS rows into a weekly/monthly bar-chart series.

Pure data shaping — no network, no rendering. The series is fed to
``chart_renderer.render_bar_chart`` the same way Sales Analysis uses
``chart_data.build_analysis_series``.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from app.services.approvals import DEFAULT_COLS, _cell, parse_amount, parse_date

_MONTH_ABBR = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)


def _sunday_of(day: date) -> date:
    return day + timedelta(days=(6 - day.weekday()))


def _last_completed_sunday(today: date) -> date:
    return today - timedelta(days=today.weekday() + 1)


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    idx = year * 12 + (month - 1) + delta
    return idx // 12, idx % 12 + 1


def _iter_deals(values: list[list[str]], cols: dict[str, int]):
    for row in values:
        approved = parse_date(_cell(row, cols["date_approved"]))
        if approved is None:
            continue
        if not _cell(row, cols["client"]):
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
    monthly_months: int = 5,
) -> list[tuple[str, float]]:
    """Return ``[(label, amount), …]`` oldest-first.

    ``kind`` is ``"weekly"`` or ``"monthly"``. All-zero series returns ``[]``
    so the CLI skips posting.
    """
    if kind not in ("weekly", "monthly"):
        raise ValueError(f"kind must be 'weekly' or 'monthly'; got {kind!r}")
    cols = cols or DEFAULT_COLS
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
    last_sunday = _last_completed_sunday(today)
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
    last_prev = today.replace(day=1) - timedelta(days=1)
    completed: list[tuple[int, int]] = []
    for i in range(n - 1, -1, -1):
        completed.append(_shift_month(last_prev.year, last_prev.month, -i))
    buckets = {key: 0.0 for key in completed}
    current_key = (today.year, today.month)
    current_total = 0.0
    for approved, amount in _iter_deals(values, cols):
        key = (approved.year, approved.month)
        if key in buckets:
            buckets[key] += amount
        elif key == current_key:
            current_total += amount
    series = [
        (f"{_MONTH_ABBR[month - 1]} {year}", buckets[(year, month)])
        for year, month in completed
    ]
    if current_total > 0:
        y, m = current_key
        series.append((f"{_MONTH_ABBR[m - 1]} {y}", current_total))
    return series
