from __future__ import annotations

import re
from pathlib import Path
from typing import Literal, TypedDict

from jinja2 import Environment, FileSystemLoader, select_autoescape

APP_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = APP_DIR / "templates"
THEMES_DIR = APP_DIR / "themes"

_AMOUNT_RE = re.compile(r"^-?[\d,.\s$€£%()]+$")
_TOTAL_PREFIXES = ("total", "average", "avg", "subtotal", "sum", "grand total")

RowKind = Literal["title", "header", "totals", "spacer", "data"]


class Cell(TypedDict):
    value: str
    is_amount: bool


class Row(TypedDict):
    kind: RowKind
    cells: list[Cell]
    width: int


_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


class ThemeNotFoundError(FileNotFoundError):
    pass


def _is_amount(value: str) -> bool:
    if not value:
        return False
    stripped = value.strip()
    if not stripped:
        return False
    return bool(_AMOUNT_RE.match(stripped)) and any(ch.isdigit() for ch in stripped)


def _load_theme(theme: str) -> str:
    candidate = THEMES_DIR / f"{theme}.css"
    if not candidate.exists():
        raise ThemeNotFoundError(f"Theme '{theme}' not found at {candidate}.")
    return candidate.read_text(encoding="utf-8")


def _starts_with_total(text: str) -> bool:
    lowered = text.strip().lower().rstrip(":")
    return any(lowered == p or lowered.startswith(p + " ") for p in _TOTAL_PREFIXES)


def _looks_like_rank(cells: list[Cell]) -> bool:
    """First cell is a positive integer like '1', '2', '10'."""
    if not cells:
        return False
    first = cells[0]["value"].strip()
    return bool(first) and first.isdigit()


def _collapse_spacers(rows: list[Row]) -> list[Row]:
    """Reduce consecutive spacer rows to a single spacer."""
    out: list[Row] = []
    for row in rows:
        if row["kind"] == "spacer" and out and out[-1]["kind"] == "spacer":
            continue
        out.append(row)
    return out


def classify_rows(values: list[list[str]], only_ranked: bool = False) -> list[Row]:
    """Split values into structurally-meaningful rows.

    Row kinds, applied in order:
    - 'spacer' : entirely empty row
    - 'totals' : first non-empty cell starts with Total / Average / Subtotal / Sum
    - 'title'  : exactly one non-empty, non-numeric cell (typically merged header bar)
    - 'header' : first remaining row with no amount-shaped cells
    - 'data'   : everything else

    Title and header are each emitted at most once.

    When ``only_ranked`` is true, data rows whose first cell is not a positive
    integer are removed (drops sub-totals / by-person breakdowns), and the
    resulting consecutive spacer rows are collapsed to one.
    """
    if not values:
        return []

    width = max((len(row) for row in values), default=0)
    out: list[Row] = []
    title_emitted = False
    header_emitted = False

    for raw in values:
        cells_raw = [str(c) if c is not None else "" for c in raw]
        cells_raw += [""] * (width - len(cells_raw))
        non_empty = [c for c in cells_raw if c.strip()]
        cells: list[Cell] = [{"value": c, "is_amount": _is_amount(c)} for c in cells_raw]

        if not non_empty:
            kind: RowKind = "spacer"
        elif _starts_with_total(non_empty[0]):
            kind = "totals"
        elif (
            not title_emitted
            and not header_emitted
            and len(non_empty) == 1
            and not _is_amount(non_empty[0])
        ):
            kind = "title"
            title_emitted = True
        elif not header_emitted and not any(c["is_amount"] for c in cells):
            kind = "header"
            header_emitted = True
        else:
            kind = "data"

        out.append({"kind": kind, "cells": cells, "width": width})

    if only_ranked:
        out = [r for r in out if r["kind"] != "data" or _looks_like_rank(r["cells"])]
        out = _collapse_spacers(out)
        # Strip leading and trailing spacers left behind by the filter.
        while out and out[0]["kind"] == "spacer":
            out.pop(0)
        while out and out[-1]["kind"] == "spacer":
            out.pop()

    return out


def render(
    values: list[list[str]],
    theme: str = "dark_green",
    title: str = "Report",
    only_ranked: bool = False,
) -> str:
    css = _load_theme(theme)
    rows = classify_rows(values, only_ranked=only_ranked)
    width = rows[0]["width"] if rows else 0
    template = _env.get_template("report.html.j2")
    return template.render(title=title, css=css, rows=rows, width=width)
