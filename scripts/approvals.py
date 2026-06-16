"""Standalone CLI: post the daily APPROVALS REPORT to Slack.

Same serverless pattern as scripts/snapshot.py — designed to run from GitHub
Actions (triggered by cron-job.org's workflow_dispatch) so the FastAPI layer
doesn't need to be hosted anywhere. Reuses the same service modules the
GET /reports/approvals endpoint uses (app.services.approvals + renderer /
screenshot / slack), so the rendered report is identical.

Required env (or CLI args):
  GOOGLE_APPLICATION_CREDENTIALS  path to service-account JSON
  SLACK_BOT_TOKEN                 (when --output=slack)
  SLACK_CHANNEL_ID / APPROVALS_CHANNEL_ID  target channel (when --output=slack)
Optional env:
  APPROVALS_DATE  M/D/YYYY override (default: today in REPORT_TZ)
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import get_settings
from app.services import approvals as approvals_service
from app.services.renderer import render
from app.services.screenshot import ScreenshotError, snapshot_html
from app.services.sheets import SheetAccessError, fetch_values
from app.services.slack import SlackUploadError, upload_png


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Post the daily APPROVALS REPORT.")
    parser.add_argument(
        "--date",
        default=os.getenv("APPROVALS_DATE") or None,
        help="M/D/YYYY override (or APPROVALS_DATE env). Default: today in REPORT_TZ.",
    )
    parser.add_argument(
        "--output",
        choices=["file", "slack"],
        default=os.getenv("OUTPUT", "slack"),
    )
    parser.add_argument(
        "--out-path",
        default=os.getenv("OUT_PATH", "approvals.png"),
        help="PNG destination when --output=file.",
    )
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()

    # Resolve target date (explicit override, else today in the report TZ).
    if args.date:
        target = approvals_service.parse_date(args.date)
        if target is None:
            print(f"::error::invalid date '{args.date}'; use M/D/YYYY.", file=sys.stderr)
            return 2
    else:
        try:
            tz = ZoneInfo(settings.report_tz)
        except ZoneInfoNotFoundError as exc:
            print(f"::error::bad REPORT_TZ '{settings.report_tz}': {exc}", file=sys.stderr)
            return 2
        target = datetime.now(tz).date()

    try:
        cols = settings.approvals_cols_map()
    except ValueError as exc:
        print(f"::error::config: {exc}", file=sys.stderr)
        return 2

    try:
        values = fetch_values(
            spreadsheet_id=settings.approvals_spreadsheet_id,
            range_a1=settings.approvals_range,
            sheet_name=settings.approvals_sheet_name,
            gid=settings.approvals_gid,
            source="api",
            credentials_path=settings.google_application_credentials,
        )
    except SheetAccessError as exc:
        print(f"::error::sheet_access: {exc}", file=sys.stderr)
        return 3

    report = approvals_service.build_report_matrix(values, target, cols=cols)
    target_str = approvals_service.format_date_us(target)
    print(f"Approvals for {target_str}: {report.count} row(s), total ${report.total:,.2f}.")

    if report.count == 0 and args.output == "slack":
        print(f"No approvals for {target_str}; nothing posted.")
        return 0

    html = render(report.matrix, theme="dark_green", title="APPROVALS REPORT")

    try:
        png_bytes = await snapshot_html(
            html,
            viewport_width=settings.viewport_width,
            viewport_height=settings.viewport_height,
        )
    except ScreenshotError as exc:
        print(f"::error::screenshot_failed: {exc}", file=sys.stderr)
        return 4

    if args.output == "file":
        out = Path(args.out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(png_bytes)
        print(f"Wrote {out}.")
        return 0

    channel = settings.approvals_channel_id or settings.slack_channel_id
    try:
        result = upload_png(
            png_bytes,
            token=settings.slack_bot_token,
            channel=channel,
            filename="approvals.png",
            initial_comment=f"APPROVALS REPORT — {target_str}",
        )
    except SlackUploadError as exc:
        print(f"::error::slack_upload_failed: {exc}", file=sys.stderr)
        return 5

    print(f"Uploaded to Slack: {result.get('permalink')}")
    return 0


def main() -> int:
    return asyncio.run(_run(_parse_args()))


if __name__ == "__main__":
    sys.exit(main())
