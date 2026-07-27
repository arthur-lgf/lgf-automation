"""Render a bar-chart series into a self-contained HTML page (inline SVG).

Produces the same dark, gold-titled look as the other LGF reports (see
``app/themes/dark_green.css``) but as a chart instead of a table. Everything is
inline — no chart library, no web fonts, no remote images — so Playwright's
``snapshot_html(html, selector="#chart")`` captures it reliably.

Public API: ``render_bar_chart(series, *, title, subtitle=None) -> str`` where
``series`` is ``[(label, amount), …]``.
"""
from __future__ import annotations

import math
from html import escape

# Per-bar categorical palette (echoes the Google chart's colors, tuned for a
# dark background). Cycled when there are more bars than colors.
_PALETTE = ("#b91c1c", "#256d7b", "#5b2c3f", "#d4a017", "#2f5c2f", "#1f3a5f")

_FONT = (
    '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, '
    '"Helvetica Neue", Arial, sans-serif'
)

# Layout (CSS px; the screenshot uses device_scale_factor=2 → 2× PNG). Bars and
# spacing are sized so the large (~40px) value/category labels don't collide.
_PLOT_H = 680
_BAR_W = 165
_GAP = 60
_LEFT = 250   # room for the large y-axis money labels
_RIGHT = 52
_TOP = 66     # room above the tallest bar's value label
_XLABEL_H = 92


def _format_money(value: float) -> str:
    """Whole-dollar label, e.g. ``$62,919``."""
    return f"${value:,.0f}"


def _nice_ceiling(value: float, ticks: int = 4) -> tuple[float, float]:
    """A rounded axis maximum ``>= value`` and its gridline step.

    Picks a 1 / 2 / 2.5 / 5 × 10ⁿ step so the axis reads cleanly, and guarantees
    headroom above the tallest bar so its value label never clips.
    """
    if value <= 0:
        return 1.0, 1.0
    raw = value / ticks
    magnitude = 10 ** math.floor(math.log10(raw))
    step = 10 * magnitude
    for multiple in (1, 2, 2.5, 5, 10):
        candidate = multiple * magnitude
        if candidate * ticks >= value:
            step = candidate
            break
    nmax = step * ticks
    if nmax <= value:  # exact-fit → add one step of headroom
        nmax += step
    return nmax, step


def _plot_width(n: int) -> int:
    return n * _BAR_W + (n + 1) * _GAP


def _card_width(n: int) -> int:
    """Card = svg width, floored so the title never gets clipped on tiny charts."""
    return max(_LEFT + _plot_width(n) + _RIGHT, 640)


# Page chrome. Kept in a <style> block (not inline style="") because the font
# stack contains double-quoted family names ("Segoe UI"), which would terminate a
# double-quoted style attribute early and silently drop the title styling.
_STYLE = (
    "body{margin:0;background:#07120e;}"
    "#chart{display:inline-block;background:#07120e;padding:26px;}"
    ".chart-card{background:#0a1f17;border:1px solid #16382c;border-radius:14px;"
    "box-shadow:0 12px 36px rgba(0,0,0,.55);overflow:hidden;font-family:" + _FONT + ";}"
    ".chart-title{color:#fbbf24;font-weight:800;font-size:43px;line-height:1.2;"
    "text-transform:uppercase;letter-spacing:.06em;text-align:center;"
    "padding:18px 24px;border-bottom:1px solid #ffffff;}"
    ".chart-sub{color:#a7c3b7;font-size:34px;text-align:center;padding:12px 24px 0;}"
)


def _svg(series: list[tuple[str, float]]) -> str:
    """The inner <svg> for the plotted bars, gridlines, and labels."""
    n = len(series)
    plot_w = _plot_width(n)
    width = _LEFT + plot_w + _RIGHT
    height = _TOP + _PLOT_H + _XLABEL_H
    baseline = _TOP + _PLOT_H

    max_value = max((v for _, v in series), default=0.0)
    nmax, step = _nice_ceiling(max_value)

    parts = [
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg" font-family=\'{_FONT}\'>',
        f'<rect x="{_LEFT}" y="{_TOP}" width="{plot_w}" height="{_PLOT_H}" fill="#0c241a"/>',
    ]

    # Horizontal gridlines + y-axis money labels.
    tick = 0.0
    while tick <= nmax + 1e-6:
        y = baseline - (tick / nmax) * _PLOT_H
        stroke = "#2a5a46" if tick == 0 else "#1c4a39"
        parts.append(
            f'<line x1="{_LEFT}" y1="{y:.1f}" x2="{_LEFT + plot_w}" y2="{y:.1f}" '
            f'stroke="{stroke}" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{_LEFT - 16}" y="{y + 12:.1f}" text-anchor="end" '
            f'font-size="38" fill="#a7c3b7">{_format_money(tick)}</text>'
        )
        tick += step

    # Bars with value labels above and category labels below.
    for i, (label, value) in enumerate(series):
        bar_h = (value / nmax) * _PLOT_H if nmax else 0.0
        x = _LEFT + _GAP + i * (_BAR_W + _GAP)
        y = baseline - bar_h
        color = _PALETTE[i % len(_PALETTE)]
        cx = x + _BAR_W / 2
        parts.append(
            f'<rect class="bar" x="{x:.1f}" y="{y:.1f}" width="{_BAR_W}" '
            f'height="{bar_h:.1f}" fill="{color}" rx="3"/>'
        )
        parts.append(
            f'<text x="{cx:.1f}" y="{y - 18:.1f}" text-anchor="middle" '
            f'font-size="40" font-weight="700" fill="#ffffff">{_format_money(value)}</text>'
        )
        parts.append(
            f'<text x="{cx:.1f}" y="{baseline + 58:.1f}" text-anchor="middle" '
            f'font-size="40" fill="#cbd5d1">{escape(label)}</text>'
        )

    parts.append("</svg>")
    return "".join(parts)


def render_bar_chart(
    series: list[tuple[str, float]], *, title: str, subtitle: str | None = None
) -> str:
    """Full HTML page with a gold-titled dark card wrapping the bar chart.

    The outer ``<div id="chart">`` is the screenshot crop target.
    """
    subtitle_html = (
        f'<div class="chart-sub">{escape(subtitle)}</div>' if subtitle else ""
    )
    width = _card_width(len(series))
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"/>'
        f"<title>{escape(title)}</title><style>{_STYLE}</style></head>"
        '<body><div id="chart">'
        f'<div class="chart-card" style="width:{width}px">'
        f'<div class="chart-title">{escape(title.upper())}</div>'
        f"{subtitle_html}"
        f"{_svg(series)}"
        "</div></div></body></html>"
    )
