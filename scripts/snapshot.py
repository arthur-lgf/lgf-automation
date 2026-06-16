"""Standalone CLI: fetch a Google Sheets range, screenshot it, ship the PNG.

Designed for use from GitHub Actions (or any cron-like environment) so the
FastAPI HTTP layer doesn't need to be hosted anywhere. Reuses the same
service modules the API uses.

Required env (or CLI args):
  GOOGLE_APPLICATION_CREDENTIALS  path to service-account JSON
  SLACK_BOT_TOKEN                 (when --output=slack)
  SLACK_CHANNEL_ID                (when --output=slack)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from app.config import get_settings
from app.services.renderer import classify_rows, has_data_rows, render
from app.services.screenshot import ScreenshotError, snapshot_html
from app.services.sheets import SheetAccessError, fetch_values
from app.services.slack import SlackUploadError, post_message, upload_png


def _no_data_text(values: list[list[str]], title: str) -> str:
    """Build the 'no sales' notice, including the report's date label if present."""
    header = next(
        (r for r in classify_rows(values, only_ranked=False) if r["kind"] == "header"),
        None,
    )
    label = header["cells"][1]["value"].strip() if header and len(header["cells"]) > 1 else ""
    suffix = f" ({label})" if label else ""
    return f"No sales to report for {title}{suffix}."


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a Google Sheets snapshot.")
    parser.add_argument(
        "--spreadsheet-id",
        default=os.getenv("SPREADSHEET_ID"),
        help="Google Spreadsheet ID (or SPREADSHEET_ID env).",
    )
    parser.add_argument(
        "--gid",
        type=int,
        default=int(os.getenv("GID")) if os.getenv("GID") else None,
        help="Tab numeric id (or GID env).",
    )
    parser.add_argument(
        "--sheet-name",
        default=os.getenv("SHEET_NAME"),
        help="Tab name (or SHEET_NAME env). Alternative to --gid.",
    )
    parser.add_argument(
        "--range",
        dest="range_a1",
        default=os.getenv("RANGE", "B1:J25"),
        help="A1 range, e.g. B1:J25.",
    )
    parser.add_argument("--theme", default=os.getenv("THEME", "dark_green"))
    parser.add_argument("--title", default=os.getenv("TITLE", "Report"))
    parser.add_argument("--source", choices=["api", "html"], default=os.getenv("SOURCE", "api"))
    parser.add_argument(
        "--only-ranked",
        action="store_true",
        default=os.getenv("ONLY_RANKED", "").strip().lower() in ("1", "true", "yes", "on"),
        help="Drop data rows whose first cell is not a numeric rank (keeps title, header, ranked rows, totals).",
    )
    parser.add_argument(
        "--output",
        choices=["file", "slack"],
        default=os.getenv("OUTPUT", "slack"),
    )
    parser.add_argument(
        "--out-path",
        default=os.getenv("OUT_PATH", "snapshot.png"),
        help="PNG destination when --output=file.",
    )

    args = parser.parse_args()

    if not args.spreadsheet_id:
        parser.error("--spreadsheet-id (or SPREADSHEET_ID env) is required.")
    if args.gid is None and not args.sheet_name:
        parser.error("--gid or --sheet-name (or env GID/SHEET_NAME) is required.")
    return args


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()

    try:
        values = fetch_values(
            spreadsheet_id=args.spreadsheet_id,
            range_a1=args.range_a1,
            sheet_name=args.sheet_name,
            gid=args.gid,
            source=args.source,
            credentials_path=settings.google_application_credentials,
        )
    except SheetAccessError as exc:
        print(f"::error::sheet_access: {exc}", file=sys.stderr)
        return 2

    if not values:
        print("::error::sheet_access: sheet returned no values", file=sys.stderr)
        return 2

    print(f"Fetched {len(values)} rows from {args.spreadsheet_id} ({args.range_a1}).")

    # No ranked sales -> send a short text notice instead of an empty
    # title/header-only image. (Slack output only; --output file still renders.)
    if args.output == "slack" and not has_data_rows(values, only_ranked=args.only_ranked):
        text = _no_data_text(values, args.title)
        try:
            post_message(
                token=settings.slack_bot_token,
                channel=settings.slack_channel_id,
                text=text,
            )
        except SlackUploadError as exc:
            print(f"::error::slack_post_failed: {exc}", file=sys.stderr)
            return 4
        print(f"No ranked sales; posted text instead of image: {text}")
        return 0

    html = render(values, theme=args.theme, title=args.title, only_ranked=args.only_ranked)

    try:
        png_bytes = await snapshot_html(
            html,
            viewport_width=settings.viewport_width,
            viewport_height=settings.viewport_height,
        )
    except ScreenshotError as exc:
        print(f"::error::screenshot_failed: {exc}", file=sys.stderr)
        return 3

    print(f"Captured snapshot ({len(png_bytes)} bytes).")

    if args.output == "file":
        out = Path(args.out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(png_bytes)
        print(f"Wrote {out}.")
        return 0

    try:
        result = upload_png(
            png_bytes,
            token=settings.slack_bot_token,
            channel=settings.slack_channel_id,
            filename="snapshot.png",
            initial_comment=args.title,
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
