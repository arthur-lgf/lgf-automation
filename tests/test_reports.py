import json
from datetime import date, datetime, timedelta
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
    # First data row: client, bank, rep, date approved, invoice sent, amount
    assert report.matrix[2] == ["Jason Delegado", "Chase", "Bikram", "6/15/26", "", "$11,000.0"]
    assert report.matrix[3][0] == "Salvador Mexicano"
    # Totals strip
    assert report.matrix[-2] == ["TOTAL APPROVED:", "", "", "", "", "2"]
    assert report.matrix[-1] == ["TOTAL AMOUNT APPROVED:", "", "", "", "", "$23,000.0"]


def test_build_matrix_no_rows_for_other_day():
    report = approvals_service.build_report_matrix(_rows(), date(2000, 1, 1))
    assert report.count == 0
    assert report.total == 0.0
    assert report.matrix[-1] == ["TOTAL AMOUNT APPROVED:", "", "", "", "", "$0.0"]


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
    assert report.matrix[2][5] == "$0.0"  # unparseable amount -> $0.0 (last col)
    assert report.matrix[-1] == ["TOTAL AMOUNT APPROVED:", "", "", "", "", "$0.0"]


def test_build_matrix_range_filters_and_sorts():
    # 6/9–6/15 captures Old Deal (6/10) + the two 6/15 rows; sorted chronologically.
    report = approvals_service.build_report_matrix(
        _rows(), date(2026, 6, 9), date(2026, 6, 15)
    )
    assert report.count == 3
    assert report.total == 28000.0
    assert report.is_range is True
    assert report.matrix[0] == ["APPROVALS REPORT — 6/9/2026 – 6/15/2026"]
    # Chronological: 6/10 first, then the two 6/15 rows in original sheet order.
    assert [r[0] for r in report.matrix[2:5]] == [
        "Old Deal",
        "Jason Delegado",
        "Salvador Mexicano",
    ]
    assert report.matrix[2][3] == "6/10/26"  # normalized date-approved cell
    assert report.matrix[-2] == ["TOTAL APPROVED:", "", "", "", "", "3"]
    assert report.matrix[-1] == ["TOTAL AMOUNT APPROVED:", "", "", "", "", "$28,000.0"]


# --- Unit tests: weekly REP leaderboard --------------------------------------


def _lb_row(date_approved: str, client: str, amount: str, rep: str) -> list[str]:
    """Build one APPS-shaped row (cols: date_approved=1, client=4, amount=8, rep=11)."""
    r = [""] * 12
    r[1], r[4], r[8], r[11] = date_approved, client, amount, rep
    return r


def test_leaderboard_aggregates_and_ranks_by_amount():
    rows = [
        _lb_row("6/9/2026", "Client A", "$10,000.00", "Alice"),
        _lb_row("6/10/2026", "Client B", "$5,000.00", "Bob"),
        _lb_row("6/11/2026", "Client C", "$8,000.00", "Alice"),
        _lb_row("6/12/2026", "Client D", "$3,000.00", "Bob"),
        _lb_row("6/13/2026", "Client E", "$1,000.00", "Carol"),
        _lb_row("6/13/2026", "", "$2,500.00", "Bob"),  # blank client -> dropped
        _lb_row("6/20/2026", "Out Of Range", "$99,000.00", "Alice"),  # outside window
    ]
    report = approvals_service.build_rep_leaderboard(
        rows, date(2026, 6, 8), date(2026, 6, 14),
        title="WEEKLY APPROVALS REPORT — 6/8/2026 – 6/14/2026",
    )
    # Alice 18000 (2 deals), Bob 8000 (2), Carol 1000 (1).
    assert report.count == 5  # total deals counted
    assert report.total == 27000.0
    assert report.matrix[0] == ["WEEKLY APPROVALS REPORT — 6/8/2026 – 6/14/2026"]
    assert approvals_service.LEADERBOARD_HEADER == ["RANK", "REP", "QTY", "AMOUNT"]
    assert report.matrix[1] == approvals_service.LEADERBOARD_HEADER
    # Ranked by total amount, descending.
    assert report.matrix[2] == ["1", "Alice", "2", "$18,000.0"]
    assert report.matrix[3] == ["2", "Bob", "2", "$8,000.0"]
    assert report.matrix[4] == ["3", "Carol", "1", "$1,000.0"]
    # Single TOTAL row: grand deal count in the label, grand amount on the right.
    assert report.matrix[-1] == ["", "TOTAL (5 DEALS)", "", "$27,000.0"]


def test_leaderboard_ranks_by_amount_not_qty():
    # Bob has more deals but a lower total -> Alice (one big deal) ranks first.
    rows = [
        _lb_row("6/9/2026", "C1", "$1,000.00", "Bob"),
        _lb_row("6/10/2026", "C2", "$1,000.00", "Bob"),
        _lb_row("6/11/2026", "C3", "$1,000.00", "Bob"),
        _lb_row("6/12/2026", "C4", "$9,000.00", "Alice"),
    ]
    report = approvals_service.build_rep_leaderboard(rows, date(2026, 6, 8), date(2026, 6, 14))
    assert report.matrix[2] == ["1", "Alice", "1", "$9,000.0"]
    assert report.matrix[3] == ["2", "Bob", "3", "$3,000.0"]


def test_leaderboard_tie_break_amount_then_qty():
    # Equal $5,000 totals: more deals ranks above fewer.
    rows = [
        _lb_row("6/9/2026", "C1", "$5,000.00", "Zoe"),   # 1 deal, $5,000
        _lb_row("6/9/2026", "C2", "$2,500.00", "Amy"),
        _lb_row("6/10/2026", "C3", "$2,500.00", "Amy"),  # 2 deals, $5,000
    ]
    report = approvals_service.build_rep_leaderboard(rows, date(2026, 6, 8), date(2026, 6, 14))
    assert report.matrix[2] == ["1", "Amy", "2", "$5,000.0"]
    assert report.matrix[3] == ["2", "Zoe", "1", "$5,000.0"]


def test_leaderboard_empty_window():
    report = approvals_service.build_rep_leaderboard(
        [_lb_row("6/9/2026", "Client A", "$10,000.00", "Alice")],
        date(2000, 1, 1), date(2000, 1, 7),
    )
    assert report.count == 0
    assert report.total == 0.0
    assert report.matrix[1] == approvals_service.LEADERBOARD_HEADER
    assert report.matrix[-1] == ["", "TOTAL (0 DEALS)", "", "$0.0"]


def test_resolve_period_today_and_yesterday():
    today = date(2026, 6, 15)
    assert approvals_service.resolve_period("today", today) == (today, today)
    assert approvals_service.resolve_period("yesterday", today) == (
        date(2026, 6, 14),
        date(2026, 6, 14),
    )


def test_resolve_period_last_week_concrete():
    # 2026-06-15 is a Monday, so the last completed week is Mon 6/8 – Sun 6/14.
    assert approvals_service.resolve_period("last-week", date(2026, 6, 15)) == (
        date(2026, 6, 8),
        date(2026, 6, 14),
    )


def test_resolve_period_last_week_invariants():
    # Whatever weekday it runs, last-week is a full Mon–Sun block in the past.
    base = date(2026, 6, 15)
    for offset in range(7):
        today = base + timedelta(days=offset)
        start, end = approvals_service.resolve_period("last-week", today)
        assert start.weekday() == 0  # Monday
        assert end.weekday() == 6  # Sunday
        assert (end - start).days == 6
        assert 1 <= (today - end).days <= 7


def test_resolve_period_unknown_raises():
    with pytest.raises(ValueError):
        approvals_service.resolve_period("fortnight", date(2026, 6, 15))


def test_caption_for_single_and_range():
    assert (
        approvals_service.caption_for(date(2026, 6, 15), date(2026, 6, 15))
        == "APPROVALS REPORT — 6/15/2026"
    )
    assert (
        approvals_service.caption_for(date(2026, 6, 8), date(2026, 6, 14), weekly=True)
        == "WEEKLY APPROVALS REPORT — 6/8/2026 – 6/14/2026"
    )


def test_resolve_period_last_month():
    # Mid-month run -> the full previous calendar month.
    assert approvals_service.resolve_period("last-month", date(2026, 6, 23)) == (
        date(2026, 5, 1),
        date(2026, 5, 31),
    )
    # Run on the 1st -> the month that just ended.
    assert approvals_service.resolve_period("last-month", date(2026, 7, 1)) == (
        date(2026, 6, 1),
        date(2026, 6, 30),
    )
    # Year boundary -> December of the prior year.
    assert approvals_service.resolve_period("last-month", date(2026, 1, 10)) == (
        date(2025, 12, 1),
        date(2025, 12, 31),
    )
    # Alias + a short (Feb, non-leap) month.
    assert approvals_service.resolve_period("monthly", date(2026, 3, 5)) == (
        date(2026, 2, 1),
        date(2026, 2, 28),
    )


def test_caption_for_monthly():
    assert (
        approvals_service.caption_for(date(2026, 5, 1), date(2026, 5, 31), monthly=True)
        == "MONTHLY APPROVALS REPORT — May 2026"
    )
    assert (
        approvals_service.caption_for(
            date(2025, 12, 1), date(2025, 12, 31), monthly=True
        )
        == "MONTHLY APPROVALS REPORT — December 2025"
    )


def test_period_kind():
    assert approvals_service.period_kind("last-week") == "weekly"
    assert approvals_service.period_kind("last-month") == "monthly"
    assert approvals_service.period_kind("monthly") == "monthly"
    assert approvals_service.period_kind("today") is None
    assert approvals_service.period_kind("yesterday") is None


def test_paginate_matrix_single_page_when_fits():
    matrix = approvals_service.build_report_matrix(_rows(), date(2026, 6, 15)).matrix
    # 2 data rows, page size 10 -> unchanged single page.
    assert approvals_service.paginate_matrix(matrix, 10) == [matrix]
    # 0 disables pagination.
    assert approvals_service.paginate_matrix(matrix, 0) == [matrix]


def test_paginate_matrix_splits_and_totals_on_last_page():
    matrix = approvals_service.build_report_matrix(
        _rows(), date(2026, 6, 9), date(2026, 6, 15)
    ).matrix  # 3 data rows
    pages = approvals_service.paginate_matrix(matrix, 2)
    assert len(pages) == 2  # 2 + 1

    # Page 1: title (part 1/2) + header + 2 data rows, NO totals.
    assert pages[0][0][0].endswith("(part 1/2)")
    assert pages[0][1] == approvals_service.HEADER
    assert [r[0] for r in pages[0][2:]] == ["Old Deal", "Jason Delegado"]
    assert not any(r[0].startswith("TOTAL") for r in pages[0])

    # Page 2: title (part 2/2) + header + last data row + the two totals rows.
    assert pages[1][0][0].endswith("(part 2/2)")
    assert pages[1][2][0] == "Salvador Mexicano"
    assert pages[1][-2] == ["TOTAL APPROVED:", "", "", "", "", "3"]
    assert pages[1][-1] == ["TOTAL AMOUNT APPROVED:", "", "", "", "", "$28,000.0"]


def test_upload_pngs_posts_one_message_with_many_files(monkeypatch: pytest.MonkeyPatch):
    captured: dict = {}

    class FakeClient:
        def __init__(self, token=None, **kwargs):
            captured["token"] = token

        def files_upload_v2(self, **kwargs):
            captured.update(kwargs)
            return {"ok": True, "files": [{"permalink": "p1"}, {"permalink": "p2"}]}

    monkeypatch.setattr(slack_service, "WebClient", FakeClient)
    result = slack_service.upload_pngs(
        [(b"a", "approvals-1.png"), (b"b", "approvals-2.png")],
        token="xoxb-test",
        channel="C123",
        initial_comment="WEEKLY APPROVALS REPORT",
    )
    assert result["ok"] is True
    assert result["count"] == 2
    # Single call -> single message; both files attached, in order.
    assert captured["channel"] == "C123"
    assert captured["initial_comment"] == "WEEKLY APPROVALS REPORT"
    assert [f["filename"] for f in captured["file_uploads"]] == [
        "approvals-1.png",
        "approvals-2.png",
    ]


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


def test_approvals_uses_separate_bot_token_when_set(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("APPROVALS_SLACK_BOT_TOKEN", "xoxb-approvals-only")
    captured: dict = {}

    def capture_upload(png_bytes: bytes, **kwargs):
        captured.update(kwargs)
        return {"ok": True, "file_id": "F1", "permalink": "p"}

    monkeypatch.setattr(slack_service, "upload_png", capture_upload)
    response = client.get("/reports/approvals", params={"output": "slack", "date": TARGET})
    assert response.status_code == 200
    assert captured["token"] == "xoxb-approvals-only"  # override beats SLACK_BOT_TOKEN


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


# --- Window selection: explicit range + named periods ------------------------


def test_approvals_route_explicit_range(client: TestClient):
    response = client.get(
        "/reports/approvals",
        params={"output": "slack", "start": "6/9/2026", "end": "6/15/2026"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["posted"] is True
    assert body["count"] == 3  # Old Deal (6/10) + Jason + Salvador (6/15)


def test_approvals_route_range_image_caption(client: TestClient, captured_html: list[str]):
    response = client.get(
        "/reports/approvals",
        params={"output": "image", "start": "6/9/2026", "end": "6/15/2026"},
    )
    assert response.status_code == 200
    html = captured_html[0]
    assert "APPROVALS REPORT — 6/9/2026 – 6/15/2026" in html
    assert "Old Deal" in html
    assert "$28,000.0" in html


def test_approvals_route_range_requires_both(client: TestClient):
    response = client.get("/reports/approvals", params={"start": "6/9/2026"})
    assert response.status_code == 422


def test_approvals_route_period_yesterday(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    class _FixedDatetime:
        @staticmethod
        def now(tz=None):
            return datetime(2026, 6, 16, 9, 0, tzinfo=tz)

    monkeypatch.setattr(reports_module, "datetime", _FixedDatetime)
    response = client.get(
        "/reports/approvals", params={"output": "slack", "period": "yesterday"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["posted"] is True
    assert body["count"] == 2  # the two 6/15/2026 rows (yesterday relative to 6/16)


def test_approvals_route_period_last_week_renders_rep_leaderboard(
    client: TestClient, captured_html: list[str], monkeypatch: pytest.MonkeyPatch
):
    # today = Monday 6/15/2026 -> last week = 6/8–6/14 -> only Old Deal (6/10),
    # whose rep is Arnold. The weekly window renders a per-REP leaderboard, so the
    # rep name + QTY/AMOUNT appear and the client name does NOT.
    class _FixedDatetime:
        @staticmethod
        def now(tz=None):
            return datetime(2026, 6, 15, 9, 0, tzinfo=tz)

    monkeypatch.setattr(reports_module, "datetime", _FixedDatetime)
    response = client.get(
        "/reports/approvals", params={"output": "image", "period": "last-week"}
    )
    assert response.status_code == 200
    html = captured_html[0]
    assert "WEEKLY APPROVALS REPORT — 6/8/2026 – 6/14/2026" in html
    assert "RANK" in html and "QTY" in html  # leaderboard header
    assert "Arnold" in html  # the rep, ranked
    assert "$5,000.0" in html
    assert "Old Deal" not in html  # client name is not shown in the leaderboard


def test_approvals_route_period_last_month_renders_monthly_leaderboard(
    client: TestClient, captured_html: list[str], monkeypatch: pytest.MonkeyPatch
):
    # today = 7/15/2026 -> last month = June 2026. Fixture June rows: Old Deal
    # (6/10, Arnold, $5k), Jason (6/15, Bikram, $11k), Salvador (6/15, Jose, $12k);
    # the blank-client 6/15 row is dropped. Leaderboard ranks by amount.
    class _FixedDatetime:
        @staticmethod
        def now(tz=None):
            return datetime(2026, 7, 15, 9, 0, tzinfo=tz)

    monkeypatch.setattr(reports_module, "datetime", _FixedDatetime)
    response = client.get(
        "/reports/approvals", params={"output": "image", "period": "last-month"}
    )
    assert response.status_code == 200
    html = captured_html[0]
    assert "MONTHLY APPROVALS REPORT — June 2026" in html
    assert "RANK" in html and "QTY" in html  # leaderboard header
    assert "Jose" in html and "Bikram" in html and "Arnold" in html  # ranked reps
    assert "TOTAL (3 DEALS)" in html
