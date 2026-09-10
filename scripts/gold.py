"""Standalone CLI: post the Monthly Gold Report to Slack.

Same pipeline as scripts/snapshot.py (fetch sheet → render → screenshot → Slack),
but only the Gold block: Sales Report tab columns V:Y. Posts to C0ATW4FSK0X
(and, for /gold, also the invoking channel if that is different).

Required env (or CLI args):
  GOOGLE_APPLICATION_CREDENTIALS  path to service-account JSON
  SLACK_BOT_TOKEN                 (when --output=slack)
  SLACK_CHANNEL_ID                primary channel (when --output=slack)
Optional:
  GOLD_SLACK_BOT_TOKEN            Gold Slack app bot (else SLACK_BOT_TOKEN)
  GOLD_CHANNEL_ID                 Gold channel (default C0ATW4FSK0X)
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

GOLD_SPREADSHEET_ID = "12glaANnP2BsQfH_kHfRlzA40JdWAU-PJgDT-56yRV8k"
GOLD_GID = 170384010
GOLD_RANGE = "V1:Y50"
GOLD_TITLE = "Monthly Gold Report"
GOLD_CHANNEL_ID = "C0ATW4FSK0X"
GOLD_CHANNEL_IDS = ("C0ATW4FSK0X",)
# Test-only extra channel: C0BFN82DDLN. Uncomment GOLD_EXTRA_CHANNEL_ID to post there.
GOLD_THEME = "gold"


def slack_token(settings) -> str | None:
    """Prefer the Gold app bot; fall back to the sales snapshot bot."""
    return settings.gold_slack_bot_token or settings.slack_bot_token


def destination_channels(*channels: str | None) -> list[str]:
    """Unique non-blank Slack channel IDs, first-seen order."""
    out: list[str] = []
    for channel in channels:
        channel = (channel or "").strip()
        if channel and channel not in out:
            out.append(channel)
    return out


def _no_data_text(values: list[list[str]], title: str) -> str:
    """Build the empty-report notice, including the date label if present."""
    header = next(
        (r for r in classify_rows(values, only_ranked=False) if r["kind"] == "header"),
        None,
    )
    label = header["cells"][1]["value"].strip() if header and len(header["cells"]) > 1 else ""
    suffix = f" ({label})" if label else ""
    return f"No gold to report for {title}{suffix}."


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Post the Monthly Gold Report.")
    parser.add_argument(
        "--spreadsheet-id",
        default=os.getenv("SPREADSHEET_ID") or GOLD_SPREADSHEET_ID,
    )
    parser.add_argument(
        "--gid",
        type=int,
        default=int(os.getenv("GID") or GOLD_GID),
    )
    parser.add_argument("--sheet-name", default=os.getenv("SHEET_NAME"))
    parser.add_argument(
        "--range",
        dest="range_a1",
        default=os.getenv("RANGE") or GOLD_RANGE,
    )
    parser.add_argument("--theme", default=os.getenv("THEME") or GOLD_THEME)
    parser.add_argument("--title", default=os.getenv("TITLE") or GOLD_TITLE)
    parser.add_argument("--source", choices=["api", "html"], default=os.getenv("SOURCE", "api"))
    parser.add_argument(
        "--only-ranked",
        action="store_true",
        default=os.getenv("ONLY_RANKED", "1").strip().lower() in ("1", "true", "yes", "on", ""),
    )
    parser.add_argument(
        "--output",
        choices=["file", "slack"],
        default=os.getenv("OUTPUT", "slack"),
    )
    parser.add_argument(
        "--out-path",
        default=os.getenv("OUT_PATH", "gold.png"),
    )
    parser.add_argument(
        "--extra-channel",
        default="",
        help="Optional extra Slack channel in addition to GOLD_CHANNEL_IDS.",
    )
    return parser.parse_args()


def _post_text(*, token: str | None, channels: list[str], text: str) -> None:
    for channel in channels:
        post_message(token=token, channel=channel, text=text)


def _post_png(
    png_bytes: bytes,
    *,
    token: str | None,
    channels: list[str],
    title: str,
) -> None:
    for channel in channels:
        result = upload_png(
            png_bytes,
            token=token,
            channel=channel,
            filename="gold.png",
            initial_comment=title,
        )
        print(f"Uploaded to Slack: {result.get('permalink')}")


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    channels = destination_channels(
        settings.slack_channel_id,
        settings.gold_channel_id,
        settings.gold_extra_channel_id,
        args.extra_channel,
    )

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

    if args.output == "slack" and not has_data_rows(values, only_ranked=args.only_ranked):
        text = _no_data_text(values, args.title)
        try:
            _post_text(token=slack_token(settings), channels=channels, text=text)
        except SlackUploadError as exc:
            print(f"::error::slack_post_failed: {exc}", file=sys.stderr)
            return 4
        print(f"No ranked gold; posted text instead of image: {text}")
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

    if not channels:
        print("::error::slack_upload_failed: no Slack channel configured", file=sys.stderr)
        return 4

    try:
        _post_png(
            png_bytes,
            token=slack_token(settings),
            channels=channels,
            title=args.title,
        )
    except SlackUploadError as exc:
        print(f"::error::slack_upload_failed: {exc}", file=sys.stderr)
        return 4

    return 0


def main() -> int:
    return asyncio.run(_run(_parse_args()))


if __name__ == "__main__":
    sys.exit(main())
