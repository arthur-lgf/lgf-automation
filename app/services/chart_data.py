"""Shape the Analysis-tab matrix into a bar-chart series (labels + amounts).

Pure data shaping — no network, no rendering — so it's unit-testable. The tab
(gid 1867438179) has two side-by-side blocks:

  weekly  cols B:E = Start Date | End Date | WE label | SALES
  monthly cols N:Q = Start Date | End Date | MONTH     | SALES

A single ``A1:Q40`` fetch covers both. Weekly rows are in range once the week has
ENDED (End Date <= today), so "the past N weeks" are completed weeks and the
in-progress current week (which reads $0 until it ends) is excluded. Monthly rows
are in range once the month has STARTED (Start Date <= today), keeping the current
month as a running partial bar. Header/blank rows are skipped naturally because
their date cell doesn't parse as a date.
"""
from __future__ import annotations

from datetime import date, timedelta

from app.services.approvals import _cell, parse_amount, parse_date

# Schedule gates the scheduled workflow evaluates in the report timezone. cron
# can't express "first Monday"/"last day", so the cadence is checked here instead.
_GATES = ("none", "first-monday", "last-day")


def gate_allows(gate: str, today: date) -> bool:
    """Whether a gated scheduled run should post on ``today``.

    - ``none``          -> always
    - ``first-monday``  -> the month's first Monday (Monday and day <= 7)
    - ``last-day``      -> the last calendar day of the month (tomorrow is the 1st)
    """
    gate = (gate or "none").strip().lower()
    if gate in ("", "none"):
        return True
    if gate == "first-monday":
        return today.weekday() == 0 and today.day <= 7
    if gate == "last-day":
        return (today + timedelta(days=1)).month != today.month
    raise ValueError(f"gate must be one of {_GATES}; got {gate!r}")

# 0-based column indices within an A1:Q fetch, per block.
# `filter_on` = which date decides a period is in range:
#   weekly  -> END date: only COMPLETED weeks show, so "the past N weeks" are the
#              N most recent finished weeks and the in-progress current week (which
#              reads $0 until it ends) is excluded.
#   monthly -> START date: the current in-progress month is kept as a running bar.
_BLOCKS = {
    "weekly": {"start": 1, "end": 2, "label": 3, "amount": 4, "filter_on": "end"},   # B,C,D,E
    "monthly": {"start": 13, "end": 14, "label": 15, "amount": 16, "filter_on": "start"},  # N,O,P,Q
}


def build_analysis_series(
    values: list[list[str]],
    kind: str,
    *,
    today: date,
    current_month_total: float | None = None,
    limit: int | None = None,
) -> list[tuple[str, float]]:
    """Return ``[(label, amount), …]`` for the given block, in sheet order.

    ``kind`` is ``"weekly"`` or ``"monthly"``. A row is in range when its
    ``filter_on`` date (weekly: END date, monthly: START date) parses and is
    ``<= today`` — so weekly shows only completed weeks while monthly keeps the
    current in-progress month.

    ``current_month_total`` (monthly only): when given, the in-progress month's
    amount is replaced by this figure so the chart's current month matches the
    live Sales Report tab instead of the Analysis tab's own (differing) value.

    ``limit`` (weekly): when set, keep only the most recent ``limit`` periods
    (the tail of the chronological series); ``None`` keeps them all.
    """
    try:
        spec = _BLOCKS[kind]
    except KeyError as exc:
        raise ValueError(
            f"kind must be one of {tuple(_BLOCKS)}; got {kind!r}"
        ) from exc

    filter_col = spec[spec["filter_on"]]
    series: list[tuple[str, float]] = []
    for row in values:
        marker = parse_date(_cell(row, filter_col))
        if marker is None or marker > today:
            continue
        label = _cell(row, spec["label"])
        if not label:
            continue
        amount = parse_amount(_cell(row, spec["amount"]))
        if kind == "monthly" and current_month_total is not None:
            start = parse_date(_cell(row, spec["start"]))
            if start is not None and (start.year, start.month) == (today.year, today.month):
                amount = current_month_total
        series.append((label, amount))
    if limit is not None:
        series = series[-limit:] if limit > 0 else []
    return series


def sum_ranked_amounts(
    values: list[list[str]], *, rank_col: int = 0, amount_col: int = 3
) -> tuple[float, int]:
    """Grand total of a ranked report block: sum the Amount column of rows whose
    first cell is a numeric rank. Returns ``(total, ranked_row_count)``.

    Used to read the Sales Report tab's (gid 170384010) current-month total from
    a ``G1:J50`` fetch (Rank | Name | Qty | Amount) without depending on the
    shifting position of the printed 'Total amount' row — and it skips the
    unranked duplicate block below the ranked one.
    """
    total = 0.0
    count = 0
    for row in values:
        if not _cell(row, rank_col).isdigit():
            continue
        total += parse_amount(_cell(row, amount_col))
        count += 1
    return total, count
