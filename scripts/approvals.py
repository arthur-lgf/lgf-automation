"""Standalone CLI: post an APPROVALS REPORT to Slack.

Same serverless pattern as scripts/snapshot.py — designed to run from GitHub
Actions (triggered by cron-job.org's workflow_dispatch) so the FastAPI layer
doesn't need to be hosted anywhere. Reuses the same service modules the
GET /reports/approvals endpoint uses (app.services.approvals + renderer /
screenshot / slack), so the rendered report is identical.

The window is one of (precedence high -> low):
  --start + --end   explicit inclusive M/D/YYYY range (backfill any span)
  --date            explicit single day
  --period          today | yesterday | last-week  (default: today)
'last-week' is the most recent completed Monday–Sunday.

Required env (or CLI args):
  GOOGLE_APPLICATION_CREDENTIALS  path to service-account JSON
  SLACK_BOT_TOKEN                 (when --output=slack)
  SLACK_CHANNEL_ID / APPROVALS_CHANNEL_ID  target channel (when --output=slack)
Optional env:
  APPROVALS_PERIOD  today | yesterday | last-week (default: today)
  APPROVALS_DATE    M/D/YYYY single-day override
  APPROVALS_START / APPROVALS_END  M/D/YYYY explicit range
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
from app.services.slack import SlackUploadError, upload_png, upload_pngs


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Post an APPROVALS REPORT.")
    parser.add_argument(
        "--period",
        choices=["today", "yesterday", "last-week", "last-month"],
        default=(os.getenv("APPROVALS_PERIOD") or "today"),
        help="Named window when no --date/--start/--end given (or APPROVALS_PERIOD env). "
        "last-week and last-month render a per-REP leaderboard.",
    )
    parser.add_argument(
        "--date",
        default=os.getenv("APPROVALS_DATE") or None,
        help="M/D/YYYY single-day override (or APPROVALS_DATE env).",
    )
    parser.add_argument(
        "--start",
        default=os.getenv("APPROVALS_START") or None,
        help="M/D/YYYY range start (with --end; or APPROVALS_START env).",
    )
    parser.add_argument(
        "--end",
        default=os.getenv("APPROVALS_END") or None,
        help="M/D/YYYY range end (with --start; or APPROVALS_END env).",
    )
    parser.add_argument(
        "--chunk-rows",
        type=int,
        default=int(os.getenv("APPROVALS_CHUNK_ROWS") or 0),
        help="Split into images of N data rows each, posted as one Slack message. "
        "0 (default) = a single image.",
    )
    parser.add_argument(
        "--output",
        choices=["file", "slack"],
        default=os.getenv("OUTPUT", "slack"),
    )
    parser.add_argument(
        "--out-path",
        default=os.getenv("OUT_PATH", "approvals.png"),
        help="PNG destination when --output=file (a -N suffix is added per page).",
    )
    return parser.parse_args()


def _resolve_window(args: argparse.Namespace, settings) -> tuple:
    """Resolve (start, end, kind) from CLI args, where kind is "weekly"/"monthly"
    (per-REP leaderboard) or None (per-approval list). Returns (None, None, None)
    on a user-input error after printing a ::error:: line."""
    parse_date = approvals_service.parse_date

    if args.start or args.end:
        if not (args.start and args.end):
            print("::error::--start and --end must be given together.", file=sys.stderr)
            return None, None, None
        start = parse_date(args.start)
        end = parse_date(args.end)
        if start is None or end is None:
            print("::error::invalid --start/--end; use M/D/YYYY.", file=sys.stderr)
            return None, None, None
        return start, end, None

    if args.date:
        target = parse_date(args.date)
        if target is None:
            print(f"::error::invalid date '{args.date}'; use M/D/YYYY.", file=sys.stderr)
            return None, None, None
        return target, target, None

    try:
        tz = ZoneInfo(settings.report_tz)
    except ZoneInfoNotFoundError as exc:
        print(f"::error::bad REPORT_TZ '{settings.report_tz}': {exc}", file=sys.stderr)
        return None, None, None
    today = datetime.now(tz).date()
    start, end = approvals_service.resolve_period(args.period, today)
    return start, end, approvals_service.period_kind(args.period)


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()

    start, end, kind = _resolve_window(args, settings)
    if start is None:
        return 2
    weekly, monthly = kind == "weekly", kind == "monthly"
    leaderboard = kind is not None  # weekly/monthly use the per-REP leaderboard

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

    caption = approvals_service.caption_for(start, end, weekly=weekly, monthly=monthly)
    # The weekly/monthly reports are a per-REP leaderboard ranked by amount; every
    # other window keeps the per-approval list.
    if leaderboard:
        report = approvals_service.build_rep_leaderboard(
            values, start, end, cols=cols, title=caption
        )
    else:
        report = approvals_service.build_report_matrix(
            values, start, end, cols=cols, title=caption
        )
    print(f"{caption}: {report.count} row(s), total ${report.total:,.2f}.")

    if report.count == 0 and args.output == "slack":
        print(f"No approvals for this window; nothing posted.")
        return 0

    # The leaderboard is a single ranked image; only the per-approval list
    # paginates (long daily/range reports). 0 = single image.
    if leaderboard:
        pages = [report.matrix]
    else:
        pages = approvals_service.paginate_matrix(report.matrix, args.chunk_rows)

    try:
        pngs: list[bytes] = []
        for page in pages:
            page_html = render(page, theme="dark_green", title=caption)
            pngs.append(
                await snapshot_html(
                    page_html,
                    viewport_width=settings.viewport_width,
                    viewport_height=settings.viewport_height,
                )
            )
    except ScreenshotError as exc:
        print(f"::error::screenshot_failed: {exc}", file=sys.stderr)
        return 4

    if args.output == "file":
        out = Path(args.out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        if len(pngs) == 1:
            out.write_bytes(pngs[0])
            print(f"Wrote {out}.")
        else:
            for i, png in enumerate(pngs, start=1):
                page_path = out.with_name(f"{out.stem}-{i}{out.suffix}")
                page_path.write_bytes(png)
                print(f"Wrote {page_path}.")
        return 0

    channel = settings.approvals_channel_id or settings.slack_channel_id
    token = settings.approvals_slack_bot_token or settings.slack_bot_token
    try:
        if len(pngs) == 1:
            result = upload_png(
                pngs[0],
                token=token,
                channel=channel,
                filename="approvals.png",
                initial_comment=caption,
            )
            print(f"Uploaded to Slack: {result.get('permalink')}")
        else:
            images = [(png, f"approvals-{i}.png") for i, png in enumerate(pngs, start=1)]
            result = upload_pngs(
                images, token=token, channel=channel, initial_comment=caption
            )
            print(f"Uploaded {result.get('count')} images to Slack as one message.")
    except SlackUploadError as exc:
        print(f"::error::slack_upload_failed: {exc}", file=sys.stderr)
        return 5

    return 0


def main() -> int:
    return asyncio.run(_run(_parse_args()))


if __name__ == "__main__":
    sys.exit(main())
