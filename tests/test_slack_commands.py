"""Slack slash-command handler logic: signature verification (with replay guard),
command parsing, and the dispatch orchestration. Pure-logic, no network — the
GitHub dispatch is injected so these never touch the API."""
import hashlib
import hmac
import urllib.parse

import pytest

from app.services import slack_commands as sc

SECRET = "8f742231b10e8888abcd99yyyzzz85a5"


def _sign(ts: str, body: str, secret: str = SECRET) -> str:
    base = f"v0:{ts}:{body}".encode()
    return "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()


def _form(**kw) -> str:
    return urllib.parse.urlencode(kw)


# --- signature verification ---------------------------------------------------


def test_verify_signature_valid():
    ts, body = "1700000000", "command=%2Fapprovals&text=last-week"
    assert sc.verify_signature(
        signing_secret=SECRET, timestamp=ts, signature=_sign(ts, body),
        body=body, now=1700000005,
    ) is True


def test_verify_signature_tampered_body_or_secret():
    ts, body = "1700000000", "command=%2Fapprovals"
    sig = _sign(ts, body)
    assert sc.verify_signature(
        signing_secret=SECRET, timestamp=ts, signature=sig,
        body=body + "&evil=1", now=1700000005,
    ) is False
    assert sc.verify_signature(
        signing_secret="wrong-secret", timestamp=ts, signature=sig,
        body=body, now=1700000005,
    ) is False


def test_verify_signature_rejects_replay():
    ts, body = "1700000000", "x=1"
    assert sc.verify_signature(
        signing_secret=SECRET, timestamp=ts, signature=_sign(ts, body),
        body=body, now=1700000000 + 301,  # older than the 300s window
    ) is False


def test_verify_signature_missing_or_bad_parts():
    assert sc.verify_signature(signing_secret=SECRET, timestamp=None, signature="x", body="b") is False
    assert sc.verify_signature(signing_secret="", timestamp="1", signature="x", body="b") is False
    assert sc.verify_signature(signing_secret=SECRET, timestamp="notint", signature="x", body="b", now=1) is False


def test_verify_signature_accepts_bytes_body():
    ts, body = "1700000000", "x=1"
    assert sc.verify_signature(
        signing_secret=SECRET, timestamp=ts, signature=_sign(ts, body),
        body=body.encode(), now=1700000005,
    ) is True


# --- command parsing ----------------------------------------------------------


def test_parse_approvals_default_and_periods():
    r = sc.parse_command("/approvals", "", "C1")
    assert r.workflow == "approvals.yml"
    assert r.inputs == {"period": "today", "channel": "C1"}
    assert "approvals" in r.report_label.lower()
    for p in ["today", "yesterday", "last-week", "last-month"]:
        assert sc.parse_command("/approvals", p, "C1").inputs["period"] == p


def test_parse_sales_default_and_periods():
    r = sc.parse_command("/sales", "", "C9")
    assert r.workflow == "sales-ondemand.yml"
    assert r.inputs == {"report": "daily", "channel": "C9"}
    assert sc.parse_command("/sales", "monthly", "C9").inputs["report"] == "monthly"


def test_parse_bad_args_raise_usage():
    with pytest.raises(sc.CommandError) as e:
        sc.parse_command("/approvals", "yearly", "C1")
    assert "today" in str(e.value)  # usage lists the valid periods
    with pytest.raises(sc.CommandError):
        sc.parse_command("/sales", "weekly", "C1")
    with pytest.raises(sc.CommandError):
        sc.parse_command("/unknown", "", "C1")


def test_parse_is_case_and_space_tolerant():
    r = sc.parse_command("/Approvals", "  LAST-WEEK ", "C1")
    assert r.inputs["period"] == "last-week"


# --- orchestration ------------------------------------------------------------


def test_handle_dispatches_on_valid_request():
    body = _form(command="/approvals", text="last-week", channel_id="C123")
    ts = "1700000000"
    calls = []

    def fake_dispatch(**kw):
        calls.append(kw)
        return 204

    resp = sc.handle_slash_request(
        raw_body=body,
        headers={"X-Slack-Signature": _sign(ts, body), "X-Slack-Request-Timestamp": ts},
        signing_secret=SECRET, github_token="ghp", repo="o/r", now=1700000003,
        dispatcher=fake_dispatch,
    )
    assert resp.status == 200
    assert len(calls) == 1
    assert calls[0]["workflow"] == "approvals.yml"
    assert calls[0]["inputs"] == {"period": "last-week", "channel": "C123"}
    assert calls[0]["repo"] == "o/r" and calls[0]["token"] == "ghp"
    assert resp.body["response_type"] == "ephemeral"
    assert "weekly approvals" in resp.body["text"].lower()


def test_handle_rejects_bad_signature():
    body = _form(command="/approvals", text="", channel_id="C1")
    ts = "1700000000"
    called = []
    resp = sc.handle_slash_request(
        raw_body=body,
        headers={"X-Slack-Signature": "v0=deadbeef", "X-Slack-Request-Timestamp": ts},
        signing_secret=SECRET, github_token="g", repo="o/r", now=1700000003,
        dispatcher=lambda **k: called.append(k) or 204,
    )
    assert resp.status == 401
    assert not called


def test_handle_bad_arg_returns_usage_without_dispatch():
    body = _form(command="/approvals", text="yearly", channel_id="C1")
    ts = "1700000000"
    called = []
    resp = sc.handle_slash_request(
        raw_body=body,
        headers={"x-slack-signature": _sign(ts, body), "x-slack-request-timestamp": ts},
        signing_secret=SECRET, github_token="g", repo="o/r", now=1700000003,
        dispatcher=lambda **k: called.append(k) or 204,
    )
    assert resp.status == 200
    assert not called
    assert "today" in resp.body["text"]


def test_handle_dispatch_failure_is_reported_not_raised():
    body = _form(command="/sales", text="monthly", channel_id="C1")
    ts = "1700000000"

    def boom(**kw):
        raise RuntimeError("github down")

    resp = sc.handle_slash_request(
        raw_body=body,
        headers={"X-Slack-Signature": _sign(ts, body), "X-Slack-Request-Timestamp": ts},
        signing_secret=SECRET, github_token="g", repo="o/r", now=1700000003,
        dispatcher=boom,
    )
    assert resp.status == 200
    assert resp.body["response_type"] == "ephemeral"
    assert "couldn't" in resp.body["text"].lower()


# --- multiple signing secrets (two Slack apps) --------------------------------

SALES_SECRET = "11aa22bb33cc44dd55ee66ff77001122"


def test_handle_accepts_request_signed_with_either_secret():
    # A request from the *sales* app (signed with SALES_SECRET) must verify even
    # though SECRET (the approvals app) is listed first.
    body = _form(command="/sales", text="monthly", channel_id="C1")
    ts = "1700000000"
    calls = []
    resp = sc.handle_slash_request(
        raw_body=body,
        headers={"X-Slack-Signature": _sign(ts, body, SALES_SECRET),
                 "X-Slack-Request-Timestamp": ts},
        signing_secret=[SECRET, SALES_SECRET], github_token="g", repo="o/r",
        now=1700000003, dispatcher=lambda **k: calls.append(k) or 204,
    )
    assert resp.status == 200
    assert len(calls) == 1 and calls[0]["workflow"] == "sales-ondemand.yml"


def test_handle_rejects_signature_from_an_unconfigured_secret():
    body = _form(command="/approvals", text="", channel_id="C1")
    ts = "1700000000"
    called = []
    resp = sc.handle_slash_request(
        raw_body=body,
        headers={"X-Slack-Signature": _sign(ts, body, "some-other-app-secret"),
                 "X-Slack-Request-Timestamp": ts},
        signing_secret=[SECRET, SALES_SECRET], github_token="g", repo="o/r",
        now=1700000003, dispatcher=lambda **k: called.append(k) or 204,
    )
    assert resp.status == 401
    assert not called


def test_handle_tolerates_blank_and_whitespace_padded_secrets():
    # Unset env vars arrive as "" and must be ignored; a real secret with a stray
    # trailing newline (copy-paste artifact) must still verify.
    body = _form(command="/approvals", text="last-week", channel_id="C1")
    ts = "1700000000"
    calls = []
    resp = sc.handle_slash_request(
        raw_body=body,
        headers={"X-Slack-Signature": _sign(ts, body), "X-Slack-Request-Timestamp": ts},
        signing_secret=["", f"  {SECRET}\n", None], github_token="g", repo="o/r",
        now=1700000003, dispatcher=lambda **k: calls.append(k) or 204,
    )
    assert resp.status == 200
    assert len(calls) == 1


def test_handle_rejects_when_no_secrets_configured():
    body = _form(command="/approvals", text="", channel_id="C1")
    ts = "1700000000"
    resp = sc.handle_slash_request(
        raw_body=body,
        headers={"X-Slack-Signature": _sign(ts, body), "X-Slack-Request-Timestamp": ts},
        signing_secret=["", None], github_token="g", repo="o/r", now=1700000003,
        dispatcher=lambda **k: 204,
    )
    assert resp.status == 401
