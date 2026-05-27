from __future__ import annotations

import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

APP_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = APP_DIR / "templates"
THEMES_DIR = APP_DIR / "themes"

_AMOUNT_RE = re.compile(r"^-?[\d,.\s$€£%()]+$")

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


def normalize_rows(values: list[list[str]]) -> tuple[list[str], list[list[dict]]]:
    if not values:
        return [], []
    header = [str(c).strip() for c in values[0]]
    width = max((len(row) for row in values), default=0)

    body: list[list[dict]] = []
    for row in values[1:]:
        padded = [str(c) for c in row] + [""] * (width - len(row))
        cells = [
            {"value": cell, "is_amount": _is_amount(cell)}
            for cell in padded
        ]
        body.append(cells)
    return header, body


def render(values: list[list[str]], theme: str = "dark_gold", title: str = "Report") -> str:
    css = _load_theme(theme)
    header, body = normalize_rows(values)
    template = _env.get_template("report.html.j2")
    return template.render(title=title, css=css, header=header, body=body)
