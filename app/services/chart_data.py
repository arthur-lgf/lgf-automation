"""Shape the Analysis-tab matrix into a bar-chart series (labels + amounts).

Pure data shaping — no network, no rendering — so it's unit-testable. The tab
(gid 1867438179) has two side-by-side blocks:

  weekly  cols B:E = Start Date | End Date | WE label | SALES
  monthly cols N:Q = Start Date | End Date | MONTH     | SALES

A single ``A1:Q40`` fetch covers both. We drop any period whose Start Date is
after ``today`` so the current partial week/month is kept but future ``$0.00``
placeholder rows are excluded (matching the Google chart). Header/blank rows are
skipped naturally because their Start-Date cell doesn't parse as a date.
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
    "weekly": {"start": 1, "label": 3, "amount": 4},   # B, D, E
    "monthly": {"start": 13, "label": 15, "amount": 16},  # N, P, Q
}


def build_analysis_series(
    values: list[list[str]], kind: str, *, today: date
) -> list[tuple[str, float]]:
    """Return ``[(label, amount), …]`` for the given block, in sheet order.

    ``kind`` is ``"weekly"`` or ``"monthly"``. Rows are included only when their
    Start Date parses and is ``<= today``.
    """
    try:
        spec = _BLOCKS[kind]
    except KeyError as exc:
        raise ValueError(
            f"kind must be one of {tuple(_BLOCKS)}; got {kind!r}"
        ) from exc

    series: list[tuple[str, float]] = []
    for row in values:
        start = parse_date(_cell(row, spec["start"]))
        if start is None or start > today:
            continue
        label = _cell(row, spec["label"])
        if not label:
            continue
        series.append((label, parse_amount(_cell(row, spec["amount"]))))
    return series
