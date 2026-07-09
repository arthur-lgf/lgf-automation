"""Standalone CLI: post the Sales Analysis bar charts (weekly / monthly) to Slack.

Same serverless pattern as scripts/snapshot.py — designed to run from GitHub
Actions. Reuses the shared services (sheets -> chart_data -> chart_renderer ->
screenshot -> slack). The Google embedded charts can't be screenshotted on a
runner, so we re-render them from the Analysis tab's data.

  --kind weekly|monthly|both   which chart(s); 'both' posts one Slack message.
  --gate none|first-monday|last-day   scheduled-cadence guard; a non-matching
        date exits 0 without posting (cron can't express these cadences).

Required env (or CLI args):
  GOOGLE_APPLICATION_CREDENTIALS  path to service-account JSON
  SLACK_BOT_TOKEN                 (when --output=slack)
  SLACK_CHANNEL_ID                (when --output=slack)
Optional env: KIND, GATE, OUTPUT, OUT_PATH, SPREADSHEET_ID, GID, RANGE.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import get_settings
from app.services.chart_data import build_analysis_series, gate_allows
from app.services.chart_renderer import render_bar_chart
from app.services.screenshot import ScreenshotError, snapshot_html
from app.services.sheets import SheetAccessError, fetch_values
from app.services.slack import SlackUploadError, post_message, upload_png, upload_pngs

_TITLES = {"weekly": "Weekly Sales Analysis", "monthly": "Monthly Sales Analysis"}


def _parse_args() -> argparse.Namespace:
    import os

    parser = argparse.ArgumentParser(description="Post Sales Analysis bar charts.")
    parser.add_argument(
        "--kind",
        choices=["weekly", "monthly", "both"],
        default=(os.getenv("KIND") or "both"),
        help="Which chart(s) to post (or KIND env). 'both' = one Slack message.",
    )
    parser.add_argument(
        "--gate",
        choices=["none", "first-monday", "last-day"],
        default=(os.getenv("GATE") or "none"),
        help="Scheduled-cadence guard (or GATE env); non-matching date posts nothing.",
    )
    parser.add_argument("--spreadsheet-id", default=os.getenv("SPREADSHEET_ID"))
    parser.add_argument(
        "--gid",
        type=int,
        default=int(os.getenv("GID")) if os.getenv("GID") else None,
    )
    parser.add_argument("--range", dest="range_a1", default=os.getenv("RANGE"))
    parser.add_argument(
        "--output", choices=["file", "slack"], default=os.getenv("OUTPUT", "slack")
    )
    parser.add_argument(
        "--out-path",
        default=os.getenv("OUT_PATH", "sales_analysis.png"),
        help="PNG destination when --output=file (a -<kind> suffix is added per chart).",
    )
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()

    try:
        tz = ZoneInfo(settings.report_tz)
    except ZoneInfoNotFoundError as exc:
        print(f"::error::bad REPORT_TZ '{settings.report_tz}': {exc}", file=sys.stderr)
        return 2
    today = datetime.now(tz).date()

    if not gate_allows(args.gate, today):
        print(f"Gate '{args.gate}' not met for {today.isoformat()}; nothing posted.")
        return 0

    spreadsheet_id = args.spreadsheet_id or settings.default_spreadsheet_id
    gid = args.gid if args.gid is not None else settings.sales_analysis_gid
    range_a1 = args.range_a1 or settings.sales_analysis_range

    try:
        values = fetch_values(
            spreadsheet_id=spreadsheet_id,
            range_a1=range_a1,
            gid=gid,
            source="api",
            credentials_path=settings.google_application_credentials,
        )
    except SheetAccessError as exc:
        print(f"::error::sheet_access: {exc}", file=sys.stderr)
        return 2
    if not values:
        print("::error::sheet_access: sheet returned no values", file=sys.stderr)
        return 2

    kinds = ["weekly", "monthly"] if args.kind == "both" else [args.kind]

    # Render each requested chart that has data.
    images: list[tuple[bytes, str, str]] = []  # (png, filename, kind)
    for kind in kinds:
        series = build_analysis_series(values, kind, today=today)
        if not series:
            print(f"No {kind} sales-analysis data; skipping that chart.")
            continue
        subtitle = f"{series[0][0]} – {series[-1][0]}"
        html = render_bar_chart(series, title=_TITLES[kind], subtitle=subtitle)
        try:
            png = await snapshot_html(
                html,
                selector="#chart",
                viewport_width=settings.viewport_width,
                viewport_height=settings.viewport_height,
            )
        except ScreenshotError as exc:
            print(f"::error::screenshot_failed: {exc}", file=sys.stderr)
            return 3
        print(f"Captured {kind} chart ({len(png)} bytes, {len(series)} bars).")
        images.append((png, f"sales-analysis-{kind}.png", kind))

    channel = settings.sales_analysis_channel_id or settings.slack_channel_id
    token = settings.sales_analysis_slack_bot_token or settings.slack_bot_token

    if not images:
        # Nothing had data (e.g. a brand-new month before any sales).
        if args.output == "slack":
            try:
                post_message(
                    token=token, channel=channel, text="No sales analysis data yet."
                )
            except SlackUploadError as exc:
                print(f"::error::slack_post_failed: {exc}", file=sys.stderr)
                return 4
        print("No charts had data; nothing to render.")
        return 0

    if args.output == "file":
        out = Path(args.out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        for png, _filename, kind in images:
            page_path = out.with_name(f"{out.stem}-{kind}{out.suffix}")
            page_path.write_bytes(png)
            print(f"Wrote {page_path}.")
        return 0

    try:
        if len(images) == 1:
            png, filename, kind = images[0]
            result = upload_png(
                png,
                token=token,
                channel=channel,
                filename=filename,
                initial_comment=f":bar_chart: *{_TITLES[kind]}*",
            )
            print(f"Uploaded to Slack: {result.get('permalink')}")
        else:
            result = upload_pngs(
                [(png, filename) for png, filename, _ in images],
                token=token,
                channel=channel,
                initial_comment=":bar_chart: *Sales Analysis* — weekly & monthly",
            )
            print(f"Uploaded {result.get('count')} charts to Slack as one message.")
    except SlackUploadError as exc:
        print(f"::error::slack_upload_failed: {exc}", file=sys.stderr)
        return 4

    return 0


def main() -> int:
    return asyncio.run(_run(_parse_args()))


if __name__ == "__main__":
    sys.exit(main())
