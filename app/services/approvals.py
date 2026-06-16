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
from datetime import date, datetime
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
    target_date: date


def build_report_matrix(
    values: list[list[str]],
    target_date: date,
    cols: Optional[dict[str, int]] = None,
    title: Optional[str] = None,
) -> ApprovalsReport:
    """Filter APPS rows to ``target_date`` approvals and shape the report matrix.

    Returns an :class:`ApprovalsReport`; ``matrix`` is renderer-ready:
    title row, header row, ranked data rows, then two totals rows.
    """
    cols = cols or DEFAULT_COLS

    matched: list[tuple[list[str], date]] = []
    for row in values:
        approved = parse_date(_cell(row, cols["date_approved"]))
        if approved is None or approved != target_date:
            continue
        if not _cell(row, cols["client"]):  # skip blank/placeholder rows
            continue
        matched.append((row, approved))

    title_text = title or f"APPROVALS REPORT — {format_date_us(target_date)}"
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
        matrix=matrix, count=count, total=total, target_date=target_date
    )
