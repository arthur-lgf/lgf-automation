"""Slack retry-handler behavior — guards the daily-report 'file_update_failed' fix.

The fix relies on slack_sdk's request-level retry: a custom RetryHandler matches
the transient ok:false body and slack_sdk re-issues the SAME HTTP request, so a
flaky files.completeUploadExternal is re-finalized with the same file_id (no
duplicate post). These tests pin the match logic and the client wiring.
"""
from slack_sdk.http_retry.response import HttpResponse

from app.services import slack as slack_service


def _resp(error: str | None = None, status: int = 200) -> HttpResponse:
    body = {"ok": error is None}
    if error is not None:
        body["error"] = error
    return HttpResponse(status_code=status, headers={}, body=body)


def test_retry_handler_retries_transient_body_errors():
    handler = slack_service.TransientSlackErrorRetryHandler()
    for code in [
        "file_update_failed",
        "internal_error",
        "fatal_error",
        "service_unavailable",
        "backend_error",
        "request_timeout",
    ]:
        assert (
            handler._can_retry(state=None, request=None, response=_resp(error=code)) is True
        ), code


def test_retry_handler_fails_fast_on_client_errors_and_success():
    handler = slack_service.TransientSlackErrorRetryHandler()
    # Real config errors must NOT be retried — they'd never succeed.
    assert handler._can_retry(state=None, request=None, response=_resp(error="channel_not_found")) is False
    assert handler._can_retry(state=None, request=None, response=_resp(error="not_in_channel")) is False
    assert handler._can_retry(state=None, request=None, response=_resp(error="missing_scope")) is False
    # A clean ok:true response is not retried.
    assert handler._can_retry(state=None, request=None, response=_resp()) is False
    # No response (connection-error path) is handled by other handlers, not this one.
    assert handler._can_retry(state=None, request=None, response=None) is False


def test_slack_clients_built_with_transient_retry_handler(monkeypatch):
    captured: dict = {}

    class FakeClient:
        def __init__(self, token=None, **kwargs):
            captured["retry_handlers"] = kwargs.get("retry_handlers")

        def files_upload_v2(self, **_kwargs):
            return {"ok": True, "file": {"id": "F1", "permalink": "p"}}

        def chat_postMessage(self, **_kwargs):
            return {"ok": True, "ts": "1.2"}

    monkeypatch.setattr(slack_service, "WebClient", FakeClient)

    def has_transient(handlers) -> bool:
        return handlers is not None and any(
            isinstance(h, slack_service.TransientSlackErrorRetryHandler) for h in handlers
        )

    slack_service.upload_png(b"x", token="t", channel="C1")
    assert has_transient(captured["retry_handlers"])

    slack_service.upload_pngs([(b"x", "1.png")], token="t", channel="C1")
    assert has_transient(captured["retry_handlers"])

    slack_service.post_message(token="t", channel="C1", text="hi")
    assert has_transient(captured["retry_handlers"])
