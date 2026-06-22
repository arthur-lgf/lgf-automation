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


def resolve_period(period: str, today: date) -> tuple[date, date]:
    """Inclusive ``(start, end)`` window for a named period relative to ``today``.

    - ``today``           -> (today, today)
    - ``yesterday``       -> (today-1, today-1)
    - ``last-week``/week  -> the most recent *completed* Monday–Sunday week, so
                             running it on any day reports the week that ended
                             before the current one (run it Monday for last week).

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
    raise ValueError(f"unknown period '{period}' (use today, yesterday, or last-week)")


def caption_for(start: date, end: date, *, weekly: bool = False) -> str:
    """Caption shown on the gold title row, the page <title>, and the Slack post."""
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
