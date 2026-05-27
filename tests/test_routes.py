import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import screenshot as screenshot_service
from app.services import sheets as sheets_service
from app.services import slack as slack_service

FIXTURE = Path(__file__).parent / "fixtures" / "sample_values.json"
PNG_STUB = b"\x89PNG\r\n\x1a\nFAKE"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def _patch_services(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_fetch_values(**_kwargs):
        return json.loads(FIXTURE.read_text(encoding="utf-8"))

    async def fake_snapshot(html: str, **_kwargs):
        assert "report-table" in html
        return PNG_STUB

    def fake_upload(png_bytes: bytes, **_kwargs):
        assert png_bytes == PNG_STUB
        return {"ok": True, "file_id": "F123", "permalink": "https://slack/permalink"}

    monkeypatch.setattr(sheets_service, "fetch_values", fake_fetch_values)
    monkeypatch.setattr(screenshot_service, "snapshot_html", fake_snapshot)
    monkeypatch.setattr(slack_service, "upload_png", fake_upload)


def test_missing_required_params_returns_422(client: TestClient):
    response = client.get("/snapshots/google-sheet")
    assert response.status_code == 422


def test_missing_gid_and_sheet_name_returns_422(client: TestClient):
    response = client.get(
        "/snapshots/google-sheet",
        params={"spreadsheet_id": "abcdefghij", "range": "B1:J25"},
    )
    assert response.status_code == 422
    assert "gid" in response.text.lower()


def test_invalid_output_returns_422(client: TestClient):
    response = client.get(
        "/snapshots/google-sheet",
        params={
            "spreadsheet_id": "abcdefghij",
            "range": "B1:J25",
            "gid": 1,
            "output": "video",
        },
    )
    assert response.status_code == 422


def test_image_output_returns_png(client: TestClient):
    response = client.get(
        "/snapshots/google-sheet",
        params={
            "spreadsheet_id": "abcdefghij",
            "range": "B1:J25",
            "gid": 1,
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert response.content == PNG_STUB


def test_slack_output_returns_json(client: TestClient):
    response = client.get(
        "/snapshots/google-sheet",
        params={
            "spreadsheet_id": "abcdefghij",
            "range": "B1:J25",
            "gid": 1,
            "output": "slack",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body == {"ok": True, "file_id": "F123", "permalink": "https://slack/permalink"}


def test_sheet_access_error_returns_502(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    def boom(**_kwargs):
        raise sheets_service.SheetAccessError("no access")

    monkeypatch.setattr(sheets_service, "fetch_values", boom)
    response = client.get(
        "/snapshots/google-sheet",
        params={
            "spreadsheet_id": "abcdefghij",
            "range": "B1:J25",
            "gid": 1,
        },
    )
    assert response.status_code == 502
    assert response.json()["error"] == "sheet_access"


def test_screenshot_error_returns_500(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    async def boom(_html: str, **_kwargs):
        raise screenshot_service.ScreenshotError("playwright dead")

    monkeypatch.setattr(screenshot_service, "snapshot_html", boom)
    response = client.get(
        "/snapshots/google-sheet",
        params={
            "spreadsheet_id": "abcdefghij",
            "range": "B1:J25",
            "gid": 1,
        },
    )
    assert response.status_code == 500
    assert response.json()["error"] == "screenshot_failed"


def test_slack_error_returns_502(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    def boom(_png: bytes, **_kwargs):
        raise slack_service.SlackUploadError("bad token")

    monkeypatch.setattr(slack_service, "upload_png", boom)
    response = client.get(
        "/snapshots/google-sheet",
        params={
            "spreadsheet_id": "abcdefghij",
            "range": "B1:J25",
            "gid": 1,
            "output": "slack",
        },
    )
    assert response.status_code == 502
    assert response.json()["error"] == "slack_upload_failed"


def test_healthz(client: TestClient):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"ok": True}
