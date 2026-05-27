from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import httpx
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from lxml import html as lxml_html

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


class SheetAccessError(RuntimeError):
    pass


def _build_a1(sheet_name: Optional[str], range_a1: str) -> str:
    if sheet_name:
        if "!" in range_a1:
            return range_a1
        return f"'{sheet_name}'!{range_a1}"
    return range_a1


def fetch_values_api(
    spreadsheet_id: str,
    range_a1: str,
    sheet_name: Optional[str] = None,
    gid: Optional[int] = None,
    credentials_path: Optional[Path] = None,
) -> list[list[str]]:
    if credentials_path is None:
        raise SheetAccessError(
            "GOOGLE_APPLICATION_CREDENTIALS is not set; cannot use the Sheets API."
        )
    if not Path(credentials_path).exists():
        raise SheetAccessError(f"Service account file not found at {credentials_path}.")

    creds = service_account.Credentials.from_service_account_file(
        str(credentials_path), scopes=SCOPES
    )
    service = build("sheets", "v4", credentials=creds, cache_discovery=False)

    resolved_name = sheet_name
    if not resolved_name and gid is not None:
        try:
            meta = (
                service.spreadsheets()
                .get(spreadsheetId=spreadsheet_id, fields="sheets(properties(sheetId,title))")
                .execute()
            )
            for sheet in meta.get("sheets", []):
                props = sheet.get("properties", {})
                if props.get("sheetId") == gid:
                    resolved_name = props.get("title")
                    break
            if resolved_name is None:
                raise SheetAccessError(f"No sheet tab found with gid={gid}.")
        except HttpError as exc:
            raise SheetAccessError(f"Failed to read sheet metadata: {exc}") from exc

    a1 = _build_a1(resolved_name, range_a1)

    try:
        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=a1, valueRenderOption="FORMATTED_VALUE")
            .execute()
        )
    except HttpError as exc:
        raise SheetAccessError(f"Failed to read range '{a1}': {exc}") from exc

    return result.get("values", []) or []


_RANGE_RE = re.compile(r"^([A-Z]+)(\d+):([A-Z]+)(\d+)$", re.IGNORECASE)


def fetch_values_html(
    spreadsheet_id: str,
    range_a1: str,
    gid: Optional[int] = None,
) -> list[list[str]]:
    if not _RANGE_RE.match(range_a1):
        raise SheetAccessError(f"Invalid range for HTML fallback: '{range_a1}'.")

    url = (
        f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/gviz/tq"
        f"?tqx=out:html&range={range_a1}"
    )
    if gid is not None:
        url += f"&gid={gid}"

    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise SheetAccessError(f"HTML fetch failed: {exc}") from exc

    doc = lxml_html.fromstring(response.text)
    rows: list[list[str]] = []
    for tr in doc.xpath("//table//tr"):
        cells = [
            (td.text_content() or "").strip()
            for td in tr.xpath(".//td|.//th")
        ]
        if cells:
            rows.append(cells)
    return rows


def fetch_values(
    spreadsheet_id: str,
    range_a1: str,
    sheet_name: Optional[str] = None,
    gid: Optional[int] = None,
    source: str = "api",
    credentials_path: Optional[Path] = None,
) -> list[list[str]]:
    if source == "html":
        return fetch_values_html(spreadsheet_id, range_a1, gid=gid)
    return fetch_values_api(
        spreadsheet_id,
        range_a1,
        sheet_name=sheet_name,
        gid=gid,
        credentials_path=credentials_path,
    )
