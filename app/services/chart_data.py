"""Shape the Analysis-tab matrix into a bar-chart series (labels + amounts).

Pure data shaping — no network, no rendering — so it's unit-testable. The tab
(gid 1867438179) has two side-by-side blocks:

  weekly  cols B:E = Start Date | End Date | WE label | SALES
  monthly cols N:Q = Start Date | End Date | MONTH     | SALES

A single ``A1:Q40`` fetch covers both. Each period is COMPLETED (End Date <=
today), CURRENT (started but not ended), or FUTURE (skipped). Charts show the most
recent N completed periods; the monthly chart additionally appends the current
in-progress month when it has data, so it reads as "the past N months + current
month (if any sales)". The weekly chart shows completed weeks only. Header/blank
rows are skipped because their date cell doesn't parse as a date.
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
_BLOCKS = {
    "weekly": {"start": 1, "end": 2, "label": 3, "amount": 4},   # B,C,D,E
    "monthly": {"start": 13, "end": 14, "label": 15, "amount": 16},  # N,O,P,Q
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

    ``kind`` is ``"weekly"`` or ``"monthly"``. Each row is classified by its dates
    relative to ``today``: COMPLETED (End Date <= today), CURRENT (started but not
    ended), or FUTURE (Start Date > today, skipped). The series is the most recent
    ``limit`` COMPLETED periods; for monthly the CURRENT (in-progress) month is
    then appended when it has data (amount > 0). Weekly never appends the current
    week, so "the past N weeks" are completed weeks only.

    ``current_month_total`` (monthly only): when given, the current month's amount
    is replaced by this figure so the chart matches the live Sales Report tab
    instead of the Analysis tab's own (differing) value.

    ``limit``: keep only the most recent ``limit`` completed periods; ``None``
    keeps them all.
    """
    try:
        spec = _BLOCKS[kind]
    except KeyError as exc:
        raise ValueError(
            f"kind must be one of {tuple(_BLOCKS)}; got {kind!r}"
        ) from exc

    completed: list[tuple[str, float]] = []
    current: tuple[str, float] | None = None
    for row in values:
        start = parse_date(_cell(row, spec["start"]))
        if start is None:  # header/blank row
            continue
        label = _cell(row, spec["label"])
        if not label:
            continue
        amount = parse_amount(_cell(row, spec["amount"]))
        if (
            kind == "monthly"
            and current_month_total is not None
            and (start.year, start.month) == (today.year, today.month)
        ):
            amount = current_month_total
        end = parse_date(_cell(row, spec["end"]))
        if end is not None and end <= today:
            completed.append((label, amount))  # week/month fully ended
        elif start <= today:
            current = (label, amount)  # started but not ended = in progress
        # else: future period -> skip

    if limit is not None:
        completed = completed[-limit:] if limit > 0 else []
    if kind == "monthly" and current is not None and current[1] > 0:
        completed.append(current)
    return completed


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
