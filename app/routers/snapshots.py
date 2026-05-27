from __future__ import annotations

from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse

from app.config import Settings, get_settings
from app.services import screenshot as screenshot_service
from app.services import sheets as sheets_service
from app.services import slack as slack_service
from app.services.renderer import ThemeNotFoundError, render

router = APIRouter(prefix="/snapshots", tags=["snapshots"])


def _settings_dep() -> Settings:
    return get_settings()


@router.get("/google-sheet")
async def google_sheet_snapshot(
    settings: Annotated[Settings, Depends(_settings_dep)],
    spreadsheet_id: str = Query(..., min_length=10, description="Google Sheets ID"),
    range: str = Query(..., min_length=2, description="A1 range, e.g. B1:J25"),
    gid: Optional[int] = Query(default=None),
    sheet_name: Optional[str] = Query(default=None),
    theme: str = Query(default="dark_gold"),
    output: Literal["image", "slack"] = Query(default="image"),
    source: Literal["api", "html"] = Query(default="api"),
    title: str = Query(default="Report"),
) -> Response:
    if gid is None and not sheet_name:
        raise HTTPException(
            status_code=422,
            detail="Provide either 'gid' or 'sheet_name'.",
        )

    try:
        values = sheets_service.fetch_values(
            spreadsheet_id=spreadsheet_id,
            range_a1=range,
            sheet_name=sheet_name,
            gid=gid,
            source=source,
            credentials_path=settings.google_application_credentials,
        )
    except sheets_service.SheetAccessError as exc:
        return JSONResponse(
            status_code=502,
            content={"error": "sheet_access", "detail": str(exc)},
        )

    if not values:
        return JSONResponse(
            status_code=502,
            content={"error": "sheet_access", "detail": "Sheet returned no values."},
        )

    try:
        html = render(values, theme=theme, title=title)
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
            headers={"Content-Disposition": 'inline; filename="snapshot.png"'},
        )

    try:
        result = slack_service.upload_png(
            png_bytes,
            token=settings.slack_bot_token,
            channel=settings.slack_channel_id,
            filename="snapshot.png",
            initial_comment=title,
        )
    except slack_service.SlackUploadError as exc:
        return JSONResponse(
            status_code=502,
            content={"error": "slack_upload_failed", "detail": str(exc)},
        )

    return JSONResponse(status_code=200, content=result)
