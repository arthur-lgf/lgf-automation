"""Build the daily "APPROVALS REPORT" values matrix from raw APPS rows.

Pure data shaping only — no network, no rendering. The matrix it returns is
fed straight into ``app.services.renderer.render`` (dark_green theme), which
classifies the title / header / totals / data rows and produces the styled
green table that ``screenshot.snapshot_html`` captures.

Keeping this logic free of FastAPI / Google / Slack makes it unit-testable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

# 0-based column indices within an ``A1:L`` fetch of the APPS tab.
# (B=Date Approved, E=Client, G=Bank, I=Amount, K=Invoice Sent, L=Rep)
DEFAULT_COLS: dict[str, int] = {
    "date_approved": 1,
    "client": 4,
    "bank": 6,
    "amount": 8,
    "invoice_sent": 10,
    "rep": 11,
}

# Two-word headers carry a newline so the dark_green theme (white-space: pre-line)
# breaks them onto a second line.
HEADER = ["CLIENT", "BANK", "REP", "DATE\nAPPROVED", "INVOICE\nSENT", "AMOUNT"]

# The WEEKLY report is a per-REP leaderboard instead of the per-approval list:
# each rep's deal count (QTY) and total amount, ranked by amount.
LEADERBOARD_HEADER = ["RANK", "REP", "QTY", "AMOUNT"]

# The Date-Approved column displays a 2-digit year (e.g. "8/29/25") while other
# date columns use 4-digit, so accept both. ISO is allowed for robustness.
_DATE_FORMATS = ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d")


def _cell(row: list, idx: int) -> str:
    """Safe, trailing-empty-tolerant cell read (Sheets truncates empty tails)."""
    if 0 <= idx < len(row):
        value = row[idx]
        return value.strip() if isinstance(value, str) else str(value).strip()
    return ""


def parse_date(text: str) -> Optional[date]:
    """Parse a sheet date string into a ``date``; ``None`` if not a date.

    Tolerant of non-zero-padded and 2- or 4-digit years. Header cells and blanks
    return ``None`` and are naturally filtered out by the date match.
    """
    text = (text or "").strip()
    if not text:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_amount(text: str) -> float:
    """Parse a currency string like ``$11,000.00`` (or ``(123)``) into a float."""
    text = (text or "").strip()
    if not text:
        return 0.0
    negative = text.startswith("(") and text.endswith(")")
    cleaned = re.sub(r"[^0-9.\-]", "", text)
    # Collapse stray characters that don't form a number.
    if cleaned in ("", "-", ".", "-.", "."):
        return 0.0
    try:
        value = float(cleaned)
    except ValueError:
        return 0.0
    return -value if negative else value


def format_date_us(value: date) -> str:
    """Render a date as ``M/D/YYYY`` (no zero padding), matching the report."""
    return f"{value.month}/{value.day}/{value.year}"


def format_date_short(value: date) -> str:
    """Render a date as ``M/D/YY`` (2-digit year), e.g. ``6/15/26``."""
    return f"{value.month}/{value.day}/{value.year % 100:02d}"


@dataclass
class ApprovalsReport:
    matrix: list[list[str]]
    count: int
    total: float
    start_date: date
    end_date: date

    @property
    def is_range(self) -> bool:
        return self.start_date != self.end_date


# Named-period aliases accepted by ``resolve_period``.
_WEEKLY_ALIASES = {"last-week", "week", "weekly"}
_MONTHLY_ALIASES = {"last-month", "month", "monthly"}

# Locale-independent month names for the monthly caption (e.g. "May 2026").
_MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


def resolve_period(period: str, today: date) -> tuple[date, date]:
    """Inclusive ``(start, end)`` window for a named period relative to ``today``.

    - ``today``           -> (today, today)
    - ``yesterday``       -> (today-1, today-1)
    - ``last-week``/week  -> the most recent *completed* Monday–Sunday week, so
                             running it on any day reports the week that ended
                             before the current one (run it Monday for last week).
    - ``last-month``/month -> the full previous calendar month (1st..last day), so
                             running it on the 1st reports the month that just
                             ended.

    Raises ``ValueError`` for an unknown period name.
    """
    p = period.strip().lower()
    if p == "today":
        return today, today
    if p == "yesterday":
        y = today - timedelta(days=1)
        return y, y
    if p in _WEEKLY_ALIASES:
        # weekday(): Mon=0 .. Sun=6. The most recent Sunday strictly before today
        # is today-(weekday+1); that week's Monday is six days earlier.
        last_sunday = today - timedelta(days=today.weekday() + 1)
        last_monday = last_sunday - timedelta(days=6)
        return last_monday, last_sunday
    if p in _MONTHLY_ALIASES:
        # Step back to the 1st of this month, then one day into the prior month;
        # that month's 1st..last day is the previous calendar month.
        first_of_this = today.replace(day=1)
        last_prev = first_of_this - timedelta(days=1)
        first_prev = last_prev.replace(day=1)
        return first_prev, last_prev
    raise ValueError(
        f"unknown period '{period}' (use today, yesterday, last-week, or last-month)"
    )


def period_kind(period: str) -> Optional[str]:
    """Classify a named period for caption/format selection: ``"weekly"`` and
    ``"monthly"`` render the per-REP leaderboard; other periods (daily/range)
    render the per-approval list. Returns ``None`` for non-summary periods."""
    p = period.strip().lower()
    if p in _WEEKLY_ALIASES:
        return "weekly"
    if p in _MONTHLY_ALIASES:
        return "monthly"
    return None


def caption_for(
    start: date, end: date, *, weekly: bool = False, monthly: bool = False
) -> str:
    """Caption shown on the gold title row, the page <title>, and the Slack post."""
    if monthly:
        # A month is labeled by its name, not a date range (e.g. "May 2026").
        return f"MONTHLY APPROVALS REPORT — {_MONTH_NAMES[start.month - 1]} {start.year}"
    label = "WEEKLY APPROVALS REPORT" if weekly else "APPROVALS REPORT"
    if start == end:
        return f"{label} — {format_date_us(start)}"
    return f"{label} — {format_date_us(start)} – {format_date_us(end)}"


def paginate_matrix(
    matrix: list[list[str]], rows_per_page: int
) -> list[list[list[str]]]:
    """Split a report matrix into page matrices of <= ``rows_per_page`` data rows.

    Each page is ``[title, HEADER, *rows]``; only the final page carries the two
    totals rows. The page title gains a ``(part i/N)`` suffix. Returns the matrix
    unchanged (one page) when ``rows_per_page <= 0`` or it all fits on one page.
    """
    if rows_per_page <= 0 or len(matrix) < 4:
        return [matrix]
    title_row, header_row = matrix[0], matrix[1]
    totals = matrix[-2:]
    data = matrix[2:-2]
    if len(data) <= rows_per_page:
        return [matrix]

    base_title = title_row[0] if title_row else ""
    chunks = [data[i : i + rows_per_page] for i in range(0, len(data), rows_per_page)]
    total_pages = len(chunks)
    pages: list[list[list[str]]] = []
    for idx, chunk in enumerate(chunks, start=1):
        page: list[list[str]] = [
            [f"{base_title}  (part {idx}/{total_pages})"],
            list(header_row),
            *[list(r) for r in chunk],
        ]
        if idx == total_pages:
            page.extend(list(r) for r in totals)
        pages.append(page)
    return pages


def build_report_matrix(
    values: list[list[str]],
    start_date: date,
    end_date: Optional[date] = None,
    cols: Optional[dict[str, int]] = None,
    title: Optional[str] = None,
) -> ApprovalsReport:
    """Filter APPS rows to approvals within ``[start_date, end_date]`` (inclusive)
    and shape the renderer-ready matrix: title row, header row, data rows sorted
    by approval date, then two totals rows.

    ``end_date=None`` (or equal to ``start_date``) yields a single-day report,
    byte-identical to the original daily report (a single date can't reorder).
    """
    cols = cols or DEFAULT_COLS
    lo = start_date
    hi = start_date if end_date is None else end_date
    if hi < lo:
        lo, hi = hi, lo

    matched: list[tuple[list[str], date]] = []
    for row in values:
        approved = parse_date(_cell(row, cols["date_approved"]))
        if approved is None or not (lo <= approved <= hi):
            continue
        if not _cell(row, cols["client"]):  # skip blank/placeholder rows
            continue
        matched.append((row, approved))

    # Chronological order. Stable sort, so a single-day report keeps sheet order.
    matched.sort(key=lambda item: item[1])

    title_text = title or caption_for(lo, hi)
    matrix: list[list[str]] = [[title_text], list(HEADER)]

    total = 0.0
    for row, approved in matched:
        amount_val = parse_amount(_cell(row, cols["amount"]))
        total += amount_val
        matrix.append(
            [
                _cell(row, cols["client"]),
                _cell(row, cols["bank"]).replace(" ", "\n"),  # break multi-word banks
                _cell(row, cols["rep"]),
                format_date_short(approved),  # normalized M/D/YY
                _cell(row, cols["invoice_sent"]),
                f"${amount_val:,.1f}",  # rounded to 1 decimal
            ]
        )

    count = len(matched)
    matrix.append(["TOTAL APPROVED:", "", "", "", "", str(count)])
    matrix.append(
        ["TOTAL AMOUNT APPROVED:", "", "", "", "", f"${total:,.1f}"]
    )

    return ApprovalsReport(
        matrix=matrix, count=count, total=total, start_date=lo, end_date=hi
    )


def build_rep_leaderboard(
    values: list[list[str]],
    start_date: date,
    end_date: Optional[date] = None,
    cols: Optional[dict[str, int]] = None,
    title: Optional[str] = None,
) -> ApprovalsReport:
    """Aggregate approvals in ``[start_date, end_date]`` (inclusive) into a per-REP
    leaderboard ranked by total amount — the shape used for the WEEKLY report.

    Each data row is ``[rank, rep, qty, amount]``: how many deals that rep got
    approved in the window and their summed amount, ordered by amount descending
    (ties broken by more deals, then rep name A–Z). A single ``TOTAL`` row carries
    the grand QTY and amount in their own columns (RANK left blank so the renderer
    classifies it as a totals row).

    The matched set matches :func:`build_report_matrix` exactly (Date-Approved in
    the window AND a non-blank Client cell), so the leaderboard's grand totals
    equal the per-approval report's for the same window. A blank Rep is grouped
    under ``"UNASSIGNED"``.
    """
    cols = cols or DEFAULT_COLS
    lo = start_date
    hi = start_date if end_date is None else end_date
    if hi < lo:
        lo, hi = hi, lo

    # rep -> [qty, amount]; running grand totals mirror build_report_matrix.
    by_rep: dict[str, list] = {}
    total_qty = 0
    total_amount = 0.0
    for row in values:
        approved = parse_date(_cell(row, cols["date_approved"]))
        if approved is None or not (lo <= approved <= hi):
            continue
        if not _cell(row, cols["client"]):  # skip blank/placeholder rows
            continue
        rep = _cell(row, cols["rep"]) or "UNASSIGNED"
        amount = parse_amount(_cell(row, cols["amount"]))
        bucket = by_rep.setdefault(rep, [0, 0.0])
        bucket[0] += 1
        bucket[1] += amount
        total_qty += 1
        total_amount += amount

    # Rank by amount desc; break ties by more deals, then rep name (stable, A–Z).
    ranked = sorted(by_rep.items(), key=lambda kv: (-kv[1][1], -kv[1][0], kv[0]))

    title_text = title or caption_for(lo, hi, weekly=True)
    matrix: list[list[str]] = [[title_text], list(LEADERBOARD_HEADER)]
    for rank, (rep, (qty, amount)) in enumerate(ranked, start=1):
        matrix.append([str(rank), rep, str(qty), f"${amount:,.1f}"])
    # The renderer merges every amount-shaped cell on a totals row, so the grand
    # deal count goes in the label (keeping the amount alone, right-aligned).
    matrix.append(["", f"TOTAL ({total_qty} DEALS)", "", f"${total_amount:,.1f}"])

    return ApprovalsReport(
        matrix=matrix, count=total_qty, total=total_amount, start_date=lo, end_date=hi
    )
