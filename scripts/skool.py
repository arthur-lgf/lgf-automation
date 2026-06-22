"""Standalone CLI: capture the Skool community dashboard and post it to Slack.

Designed for use from GitHub Actions (or any cron-like environment). Reuses
the same service modules the API uses.

Required env (or CLI args):
  SKOOL_AUTH_TOKEN       Skool session auth token (cookie value)
  SKOOL_DASHBOARD_URL    Full URL of the Skool dashboard page

Optional env:
  SKOOL_CAPTURE_SELECTOR  CSS selector for the dashboard panel (default: body)
  SKOOL_CHANNEL_ID        Slack channel to post to (falls back to SLACK_CHANNEL_ID)
  SKOOL_SLACK_BOT_TOKEN   Slack bot token (falls back to SLACK_BOT_TOKEN)
  OUTPUT                  "slack" (default) or "file"
  OUT_PATH                PNG destination when OUTPUT=file (default: skool.png)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import get_settings
from app.services.browser_capture import CaptureError, capture_dashboard
from app.services.slack import SlackUploadError, upload_png


def _build_caption(today: date, kpis: dict[str, str]) -> str:
    """Build the Slack caption for the Skool dashboard snapshot.

    Line 1 is always the header with non-zero-padded date.
    If kpis is non-empty, a KPI line is appended after a newline.
    """
    line1 = f":bar_chart: *Skool — LetsGetFunded PRO* — {today.month}/{today.day}/{today.year}"
    if not kpis:
        return line1
    kpi_line = " · ".join(f"{name} {value}" for name, value in kpis.items())
    return f"{line1}\n{kpi_line}"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture Skool dashboard and post to Slack.")
    parser.add_argument(
        "--url",
        default=None,
        help="Skool dashboard URL (or SKOOL_DASHBOARD_URL env).",
    )
    parser.add_argument(
        "--output",
        choices=["file", "slack"],
        default=os.getenv("OUTPUT", "slack"),
    )
    parser.add_argument(
        "--out-path",
        default=os.getenv("OUT_PATH", "skool.png"),
        help="PNG destination when --output=file.",
    )
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()

    # Resolve URL
    url = args.url or settings.skool_dashboard_url
    if not url:
        print(
            "::error::config: SKOOL_DASHBOARD_URL is not set (pass --url or set SKOOL_DASHBOARD_URL).",
            file=sys.stderr,
        )
        return 2

    # Resolve auth token
    auth_token = settings.skool_auth_token
    if not auth_token:
        print("::error::config: SKOOL_AUTH_TOKEN is not set.", file=sys.stderr)
        return 2

    # Resolve timezone and today's date
    try:
        tz = ZoneInfo(settings.report_tz)
    except ZoneInfoNotFoundError:
        print(
            f"::error::config: bad REPORT_TZ {settings.report_tz!r} — unknown timezone.",
            file=sys.stderr,
        )
        return 2
    today = datetime.now(tz).date()

    # Capture dashboard
    try:
        png, kpis = await capture_dashboard(
            url,
            auth_token=auth_token,
            cookie_domain=settings.skool_cookie_domain,
            selector=settings.skool_capture_selector,
            viewport_width=settings.viewport_width,
            viewport_height=settings.viewport_height,
            kpi_selectors=None,  # KPI card selectors unknown until the spike; capture
                                 # returns {} so the KPI line is dropped. Wire a
                                 # SKOOL_KPI_SELECTORS config as a follow-up once known.
        )
    except CaptureError as exc:
        print(f"::error::capture_failed: {exc}", file=sys.stderr)
        return 3

    caption = _build_caption(today, kpis)
    print(f"Captured dashboard ({len(png)} bytes); kpis={list(kpis)}.")

    if args.output == "file":
        out = Path(args.out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(png)
        print(f"Wrote {out}.")
        return 0

    # Slack upload
    channel = settings.skool_channel_id or settings.slack_channel_id
    token = settings.skool_slack_bot_token or settings.slack_bot_token
    try:
        result = upload_png(
            png,
            token=token,
            channel=channel,
            filename="skool.png",
            initial_comment=caption,
        )
    except SlackUploadError as exc:
        print(f"::error::slack_upload_failed: {exc}", file=sys.stderr)
        return 4

    print(f"Uploaded to Slack: {result.get('permalink')}")
    return 0


def main() -> int:
    return asyncio.run(_run(_parse_args()))


if __name__ == "__main__":
    sys.exit(main())
