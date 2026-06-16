import json
from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.routers import reports as reports_module
from app.services import approvals as approvals_service
from app.services import screenshot as screenshot_service
from app.services import sheets as sheets_service
from app.services import slack as slack_service

FIXTURE = Path(__file__).parent / "fixtures" / "apps_rows.json"
PNG_STUB = b"\x89PNG\r\n\x1a\nFAKE"
TARGET = "6/15/2026"


def _rows() -> list[list[str]]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


# --- Unit tests: pure shaping ------------------------------------------------


def test_build_matrix_filters_to_target_date():
    report = approvals_service.build_report_matrix(_rows(), date(2026, 6, 15))
    assert report.count == 2  # Jason + Salvador (blank-client row dropped)
    assert report.total == 23000.0
    assert report.matrix[0] == ["APPROVALS REPORT — 6/15/2026"]
    assert report.matrix[1] == approvals_service.HEADER
    # First data row: rank, client, bank, rep, date approved, invoice sent, amount
    assert report.matrix[2] == ["1", "Jason Delegado", "Chase", "Bikram", "6/15/26", "", "$11,000.0"]
    assert report.matrix[3][1] == "Salvador Mexicano"
    # Totals strip
    assert report.matrix[-2] == ["TOTAL APPROVED:", "", "", "", "", "", "2"]
    assert report.matrix[-1] == ["TOTAL AMOUNT APPROVED:", "", "", "", "", "", "$23,000.0"]


def test_build_matrix_no_rows_for_other_day():
    report = approvals_service.build_report_matrix(_rows(), date(2000, 1, 1))
    assert report.count == 0
    assert report.total == 0.0
    assert report.matrix[-1] == ["TOTAL AMOUNT APPROVED:", "", "", "", "", "", "$0.0"]


def test_parse_date_tolerates_year_widths():
    assert approvals_service.parse_date("6/15/26") == date(2026, 6, 15)
    assert approvals_service.parse_date("6/15/2026") == date(2026, 6, 15)
    assert approvals_service.parse_date("Date Approved") is None
    assert approvals_service.parse_date("") is None


def test_parse_amount():
    assert approvals_service.parse_amount("$11,000.00") == 11000.0
    assert approvals_service.parse_amount("") == 0.0
    assert approvals_service.parse_amount("(250.50)") == -250.50


def test_build_matrix_malformed_amount_counts_but_totals_zero():
    rows = [
        ["", "6/20/2026", "", "Approved", "Bad Amount Co", "", "Chase", "", "NOTANUMBER", "", "", "Lee"],
    ]
    report = approvals_service.build_report_matrix(rows, date(2026, 6, 20))
    assert report.count == 1
    assert report.total == 0.0
    assert report.matrix[2][6] == "$0.0"  # unparseable amount -> $0.0
    assert report.matrix[-1] == ["TOTAL AMOUNT APPROVED:", "", "", "", "", "", "$0.0"]


def test_approvals_cols_map_validates_length_and_ints():
    s = get_settings()
    s.approvals_cols = "1,4,6"  # too few
    with pytest.raises(ValueError):
        s.approvals_cols_map()
    s.approvals_cols = ""  # empty
    with pytest.raises(ValueError):
        s.approvals_cols_map()
    s.approvals_cols = "1,x,6,8,10,11"  # non-int
    with pytest.raises(ValueError):
        s.approvals_cols_map()
    s.approvals_cols = "1,4,6,8,10,11,"  # trailing comma tolerated
    assert s.approvals_cols_map()["rep"] == 11


# --- Route tests: patch the network/browser boundaries -----------------------


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def captured_html() -> list[str]:
    return []


@pytest.fixture(autouse=True)
def _patch_services(monkeypatch: pytest.MonkeyPatch, captured_html: list[str]) -> None:
    def fake_fetch_values(**_kwargs):
        return _rows()

    async def fake_snapshot(html: str, **_kwargs):
        assert "report-table" in html  # real renderer ran and produced the table
        captured_html.append(html)
        return PNG_STUB

    def fake_upload(png_bytes: bytes, **kwargs):
        assert png_bytes == PNG_STUB
        return {"ok": True, "file_id": "F999", "permalink": "https://slack/p"}

    monkeypatch.setattr(sheets_service, "fetch_values", fake_fetch_values)
    monkeypatch.setattr(screenshot_service, "snapshot_html", fake_snapshot)
    monkeypatch.setattr(slack_service, "upload_png", fake_upload)


def test_approvals_image_output(client: TestClient, captured_html: list[str]):
    response = client.get("/reports/approvals", params={"output": "image", "date": TARGET})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert response.content == PNG_STUB
    # The real renderer turned the matrix into the styled report.
    html = captured_html[0]
    assert "APPROVALS REPORT" in html
    assert "Jason Delegado" in html
    assert "$23,000.0" in html


def test_approvals_slack_output(client: TestClient):
    response = client.get("/reports/approvals", params={"output": "slack", "date": TARGET})
    assert response.status_code == 200
    body = response.json()
    assert body["posted"] is True
    assert body["count"] == 2
    assert body["file_id"] == "F999"


def test_approvals_no_rows_does_not_post(client: TestClient):
    response = client.get("/reports/approvals", params={"output": "slack", "date": "1/1/2000"})
    assert response.status_code == 200
    body = response.json()
    assert body["posted"] is False
    assert "no approvals" in body["reason"]


def test_approvals_invalid_date_returns_422(client: TestClient):
    response = client.get("/reports/approvals", params={"date": "not-a-date"})
    assert response.status_code == 422


def test_approvals_sheet_access_error_returns_502(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    def boom(**_kwargs):
        raise sheets_service.SheetAccessError("no access")

    monkeypatch.setattr(sheets_service, "fetch_values", boom)
    response = client.get("/reports/approvals", params={"output": "slack", "date": TARGET})
    assert response.status_code == 502
    assert response.json()["error"] == "sheet_access"


def test_approvals_screenshot_error_returns_500(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    async def boom(_html: str, **_kwargs):
        raise screenshot_service.ScreenshotError("playwright dead")

    monkeypatch.setattr(screenshot_service, "snapshot_html", boom)
    response = client.get("/reports/approvals", params={"output": "image", "date": TARGET})
    assert response.status_code == 500
    assert response.json()["error"] == "screenshot_failed"


def test_approvals_default_date_uses_report_tz(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """No ?date= : exercises the production path (ZoneInfo(REPORT_TZ) + now().date())."""

    class _FixedDatetime:
        @staticmethod
        def now(tz=None):
            return datetime(2026, 6, 15, 12, 0, tzinfo=tz)

    monkeypatch.setattr(reports_module, "datetime", _FixedDatetime)
    response = client.get("/reports/approvals", params={"output": "slack"})
    assert response.status_code == 200
    body = response.json()
    assert body["posted"] is True
    assert body["count"] == 2  # the two 6/15/2026 rows in the fixture


def test_approvals_bad_timezone_returns_500(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("REPORT_TZ", "Mars/Phobos")
    response = client.get("/reports/approvals", params={"output": "slack"})  # no date
    assert response.status_code == 500
    assert "tzdata" in response.json()["detail"]


def test_approvals_bad_cols_returns_500(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APPROVALS_COLS", "1,4,6")  # too few -> config error
    response = client.get("/reports/approvals", params={"output": "image", "date": TARGET})
    assert response.status_code == 500
    assert response.json()["error"] == "config"


def test_approvals_slack_error_returns_502(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    def boom(_png: bytes, **_kwargs):
        raise slack_service.SlackUploadError("bad token")

    monkeypatch.setattr(slack_service, "upload_png", boom)
    response = client.get("/reports/approvals", params={"output": "slack", "date": TARGET})
    assert response.status_code == 502
    assert response.json()["error"] == "slack_upload_failed"


def test_approvals_bad_theme_returns_422(client: TestClient):
    response = client.get(
        "/reports/approvals",
        params={"output": "image", "date": TARGET, "theme": "does_not_exist"},
    )
    assert response.status_code == 422
