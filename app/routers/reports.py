from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Annotated, Literal, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse

from app.config import Settings, get_settings
from app.services import approvals as approvals_service
from app.services import screenshot as screenshot_service
from app.services import sheets as sheets_service
from app.services import slack as slack_service
from app.services.renderer import ThemeNotFoundError, render

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["reports"])


def _settings_dep() -> Settings:
    return get_settings()


@router.get("/approvals")
async def approvals_report(
    settings: Annotated[Settings, Depends(_settings_dep)],
    output: Literal["image", "slack"] = Query(
        default="slack", description="'slack' posts the PNG; 'image' returns it."
    ),
    period: Literal["today", "yesterday", "last-week"] = Query(
        default="today",
        description="Named window used when no date/start/end given. "
        "'last-week' = most recent completed Monday–Sunday.",
    ),
    date: Optional[str] = Query(
        default=None, description="M/D/YYYY single-day override."
    ),
    start: Optional[str] = Query(
        default=None, description="M/D/YYYY range start (with end)."
    ),
    end: Optional[str] = Query(
        default=None, description="M/D/YYYY range end (with start)."
    ),
    spreadsheet_id: Optional[str] = Query(default=None),
    gid: Optional[int] = Query(default=None),
    sheet_name: Optional[str] = Query(default=None),
    range: Optional[str] = Query(default=None),
    theme: str = Query(default="dark_green"),
    channel: Optional[str] = Query(default=None),
) -> Response:
    # 1) Resolve the report window. Precedence: explicit start+end range >
    # explicit single date > named period (relative to today in the report TZ).
    weekly = False
    if start or end:
        if not (start and end):
            raise HTTPException(
                status_code=422, detail="Pass both 'start' and 'end' for a range."
            )
        win_start = approvals_service.parse_date(start)
        win_end = approvals_service.parse_date(end)
        if win_start is None or win_end is None:
            raise HTTPException(
                status_code=422, detail="Invalid start/end; use M/D/YYYY."
            )
    elif date:
        target = approvals_service.parse_date(date)
        if target is None:
            raise HTTPException(
                status_code=422, detail=f"Invalid date '{date}'; use M/D/YYYY."
            )
        win_start = win_end = target
    else:
        try:
            tz = ZoneInfo(settings.report_tz)
        except ZoneInfoNotFoundError as exc:
            raise HTTPException(
                status_code=500,
                detail=(
                    f"Time zone '{settings.report_tz}' unavailable ({exc}); "
                    "install the 'tzdata' package or pass ?date=."
                ),
            )
        today = datetime.now(tz).date()
        win_start, win_end = approvals_service.resolve_period(period, today)
        weekly = period == "last-week"

    spreadsheet = spreadsheet_id or settings.approvals_spreadsheet_id
    resolved_gid = gid if gid is not None else settings.approvals_gid
    resolved_sheet = sheet_name or settings.approvals_sheet_name
    range_a1 = range or settings.approvals_range

    # Resolve the column map early so a bad APPROVALS_COLS fails with a clear
    # message instead of an opaque KeyError deep in matrix building.
    try:
        cols = settings.approvals_cols_map()
    except ValueError as exc:
        return JSONResponse(
            status_code=500, content={"error": "config", "detail": str(exc)}
        )

    # 2) Pull the APPS rows. fetch_values is synchronous (blocking HTTP); offload
    # it so the unbounded APPS pull doesn't stall the event loop.
    try:
        values = await asyncio.to_thread(
            sheets_service.fetch_values,
            spreadsheet_id=spreadsheet,
            range_a1=range_a1,
            sheet_name=resolved_sheet,
            gid=resolved_gid,
            source="api",
            credentials_path=settings.google_application_credentials,
        )
    except sheets_service.SheetAccessError as exc:
        return JSONResponse(
            status_code=502, content={"error": "sheet_access", "detail": str(exc)}
        )

    # 3) Filter to the window's approvals and shape the renderer matrix.
    caption = approvals_service.caption_for(win_start, win_end, weekly=weekly)
    report = approvals_service.build_report_matrix(
        values, win_start, win_end, cols=cols, title=caption
    )

    # Nothing approved in the window: don't post an empty report; report the fact.
    if report.count == 0 and output == "slack":
        logger.info("No approvals for %s; nothing posted.", caption)
        return JSONResponse(
            status_code=200,
            content={"posted": False, "reason": f"no approvals for {caption}"},
        )

    # 4) Render -> screenshot.
    try:
        html = render(report.matrix, theme=theme, title=caption)
    except ThemeNotFoundError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    try:
        png_bytes = await screenshot_service.snapshot_html(
            html,
            viewport_width=settings.viewport_width,
            viewport_height=settings.viewport_height,
        )
    except screenshot_service.ScreenshotError as exc:
        return JSONResponse(
            status_code=500,
            content={"error": "screenshot_failed", "detail": str(exc)},
        )

    if output == "image":
        return Response(
            content=png_bytes,
            media_type="image/png",
            headers={"Content-Disposition": 'inline; filename="approvals.png"'},
        )

    # 5) Upload to Slack (the bot must be a member of the target channel).
    target_channel = channel or settings.approvals_channel_id or settings.slack_channel_id
    target_token = settings.approvals_slack_bot_token or settings.slack_bot_token
    try:
        result = slack_service.upload_png(
            png_bytes,
            token=target_token,
            channel=target_channel,
            filename="approvals.png",
            initial_comment=caption,
        )
    except slack_service.SlackUploadError as exc:
        return JSONResponse(
            status_code=502,
            content={"error": "slack_upload_failed", "detail": str(exc)},
        )

    return JSONResponse(
        status_code=200,
        content={"posted": True, "count": report.count, **result},
    )
