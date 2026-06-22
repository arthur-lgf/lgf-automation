"""Tests for scripts/skool.py — TDD, written before the implementation.

Import the module under test via importlib since scripts/ is not a package.
"""
from __future__ import annotations

import argparse
import importlib.util
import pathlib
import types

import pytest

from app.services.browser_capture import CaptureError, _looks_logged_out
from app.services.slack import SlackUploadError
from datetime import date

# ---------------------------------------------------------------------------
# Load skool module from file (scripts/ has no __init__.py)
# ---------------------------------------------------------------------------
_path = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "skool.py"
_spec = importlib.util.spec_from_file_location("skool_cli", _path)
skool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(skool)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stub_settings(**overrides):
    defaults = dict(
        skool_dashboard_url="https://www.skool.com/letsgetfunded-pro/-/dashboard",
        skool_auth_token="tok_test",
        skool_cookie_domain=".skool.com",
        skool_capture_selector="body",
        skool_channel_id="C_SKOOL",
        slack_channel_id="C_FALLBACK",
        skool_slack_bot_token="xoxb-skool",
        slack_bot_token="xoxb-fallback",
        viewport_width=1400,
        viewport_height=900,
        report_tz="America/New_York",
    )
    defaults.update(overrides)
    return types.SimpleNamespace(**defaults)


def _default_args(**overrides):
    defaults = dict(url=None, output="slack", out_path="skool.png")
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


# ---------------------------------------------------------------------------
# 1. _build_caption with KPIs
# ---------------------------------------------------------------------------

def test_build_caption_with_kpis():
    kpis = {"Members": "692", "MRR": "$36,645", "Engagement": "75%", "Retention": "78%"}
    result = skool._build_caption(date(2026, 6, 22), kpis)
    expected = (
        ":bar_chart: *Skool — LetsGetFunded PRO* — 6/22/2026\n"
        "Members 692 · MRR $36,645 · Engagement 75% · Retention 78%"
    )
    assert result == expected


# ---------------------------------------------------------------------------
# 2. _build_caption without KPIs
# ---------------------------------------------------------------------------

def test_build_caption_without_kpis():
    result = skool._build_caption(date(2026, 6, 22), {})
    expected = ":bar_chart: *Skool — LetsGetFunded PRO* — 6/22/2026"
    assert result == expected


# ---------------------------------------------------------------------------
# 3. _build_caption no zero-padding
# ---------------------------------------------------------------------------

def test_build_caption_no_zero_pad():
    result = skool._build_caption(date(2026, 1, 5), {})
    assert result.endswith("1/5/2026")


# ---------------------------------------------------------------------------
# 4. _run posts to Slack
# ---------------------------------------------------------------------------

async def test_run_posts_to_slack(monkeypatch):
    stub = _stub_settings()
    monkeypatch.setattr(skool, "get_settings", lambda: stub)

    captured_calls = {}

    async def fake_capture(url, *, auth_token, cookie_domain, selector,
                           viewport_width, viewport_height, kpi_selectors=None):
        return (b"PNGBYTES", {"Members": "692"})

    def fake_upload_png(png_bytes, *, token, channel, filename, initial_comment):
        captured_calls["png"] = png_bytes
        captured_calls["token"] = token
        captured_calls["channel"] = channel
        captured_calls["initial_comment"] = initial_comment
        return {"ok": True, "permalink": "p"}

    monkeypatch.setattr(skool, "capture_dashboard", fake_capture)
    monkeypatch.setattr(skool, "upload_png", fake_upload_png)

    result = await skool._run(_default_args())

    assert result == 0
    assert captured_calls["png"] == b"PNGBYTES"
    assert "Members 692" in captured_calls["initial_comment"]
    assert captured_calls["channel"] == "C_SKOOL"
    assert captured_calls["token"] == "xoxb-skool"


# ---------------------------------------------------------------------------
# 5. _run missing config returns 2
# ---------------------------------------------------------------------------

async def test_run_missing_config_returns_2(monkeypatch):
    stub = _stub_settings(skool_dashboard_url=None, skool_auth_token=None)
    monkeypatch.setattr(skool, "get_settings", lambda: stub)

    capture_called = []
    upload_called = []

    async def fake_capture(*a, **kw):
        capture_called.append(True)
        return (b"X", {})

    def fake_upload_png(*a, **kw):
        upload_called.append(True)
        return {}

    monkeypatch.setattr(skool, "capture_dashboard", fake_capture)
    monkeypatch.setattr(skool, "upload_png", fake_upload_png)

    result = await skool._run(_default_args(url=None))

    assert result == 2
    assert not capture_called
    assert not upload_called


# ---------------------------------------------------------------------------
# 6. _run output=file writes PNG
# ---------------------------------------------------------------------------

async def test_run_output_file_writes_png(monkeypatch, tmp_path):
    stub = _stub_settings()
    monkeypatch.setattr(skool, "get_settings", lambda: stub)

    async def fake_capture(url, *, auth_token, cookie_domain, selector,
                           viewport_width, viewport_height, kpi_selectors=None):
        return (b"PNGBYTES", {})

    upload_called = []

    def fake_upload_png(*a, **kw):
        upload_called.append(True)
        return {}

    monkeypatch.setattr(skool, "capture_dashboard", fake_capture)
    monkeypatch.setattr(skool, "upload_png", fake_upload_png)

    out_file = str(tmp_path / "out.png")
    result = await skool._run(_default_args(output="file", out_path=out_file))

    assert result == 0
    assert pathlib.Path(out_file).exists()
    assert pathlib.Path(out_file).read_bytes() == b"PNGBYTES"
    assert not upload_called


# ---------------------------------------------------------------------------
# 7. _run capture error returns 3
# ---------------------------------------------------------------------------

async def test_run_capture_error_returns_3(monkeypatch):
    stub = _stub_settings()
    monkeypatch.setattr(skool, "get_settings", lambda: stub)

    async def fake_capture(*a, **kw):
        raise CaptureError("session expired — refresh SKOOL_AUTH_TOKEN")

    monkeypatch.setattr(skool, "capture_dashboard", fake_capture)

    result = await skool._run(_default_args())
    assert result == 3


# ---------------------------------------------------------------------------
# 8. _run slack error returns 4
# ---------------------------------------------------------------------------

async def test_run_slack_error_returns_4(monkeypatch):
    stub = _stub_settings()
    monkeypatch.setattr(skool, "get_settings", lambda: stub)

    async def fake_capture(*a, **kw):
        return (b"PNGBYTES", {})

    def fake_upload_png(*a, **kw):
        raise SlackUploadError("channel_not_found")

    monkeypatch.setattr(skool, "capture_dashboard", fake_capture)
    monkeypatch.setattr(skool, "upload_png", fake_upload_png)

    result = await skool._run(_default_args())
    assert result == 4


# ---------------------------------------------------------------------------
# 9. _looks_logged_out parametrized
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url,expected", [
    ("https://www.skool.com/login", True),
    ("https://www.skool.com/signup", True),
    ("https://www.skool.com/letsgetfunded-pro/-/dashboard", False),
    ("https://www.skool.com/letsgetfunded-pro", False),
])
def test_looks_logged_out(url, expected):
    assert _looks_logged_out(url) == expected
