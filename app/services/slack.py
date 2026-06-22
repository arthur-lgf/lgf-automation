from __future__ import annotations

import os
from typing import Optional

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.http_retry import (
    ConnectionErrorRetryHandler,
    RateLimitErrorRetryHandler,
    RetryHandler,
)
from slack_sdk.http_retry.builtin_handlers import ServerErrorRetryHandler


class SlackUploadError(RuntimeError):
    pass


# Slack body-level errors (HTTP 200 with ok:false) that are transient server-side
# hiccups worth retrying — NOT client mistakes (channel_not_found, missing_scope…,
# which must fail fast). ``file_update_failed`` is the one the daily snapshot hit:
# the PNG bytes upload fine, then files.completeUploadExternal flakes while
# finalizing the share. See slackapi/python-slack-sdk#1730.
_TRANSIENT_SLACK_ERRORS = frozenset(
    {
        "file_update_failed",
        "internal_error",
        "fatal_error",
        "service_unavailable",
        "backend_error",
        "request_timeout",
    }
)

# Retries per transient failure (env-tunable). Total attempts = 1 + _RETRY_MAX.
_RETRY_MAX = int(os.getenv("SLACK_RETRY_MAX", "3"))


class TransientSlackErrorRetryHandler(RetryHandler):
    """Retry an HTTP-200 Slack response whose JSON body is a transient ok:false error.

    slack_sdk's retry loop re-issues the *same* failing HTTP request, so a
    ``files.completeUploadExternal`` that returned ``file_update_failed`` is
    re-finalized with the SAME file_id — idempotent, no duplicate post. (Retrying
    the whole ``files_upload_v2`` flow would mint a new file_id and risk a
    duplicate; we deliberately rely on the in-place request retry instead.)
    """

    def _can_retry(self, *, state, request, response=None, error=None) -> bool:
        return (
            response is not None
            and response.body is not None
            and response.body.get("error") in _TRANSIENT_SLACK_ERRORS
        )


def _retry_handlers() -> list[RetryHandler]:
    """Handlers shared by every Slack client we build: connection drops, HTTP 429
    (Retry-After honored), HTTP 500/503, and transient ok:false response bodies."""
    return [
        ConnectionErrorRetryHandler(max_retry_count=_RETRY_MAX),
        RateLimitErrorRetryHandler(max_retry_count=_RETRY_MAX),
        ServerErrorRetryHandler(max_retry_count=_RETRY_MAX),
        TransientSlackErrorRetryHandler(max_retry_count=_RETRY_MAX),
    ]


# Stateless handlers (per-request state lives in slack_sdk's RetryState), so one
# shared list is safe across every WebClient we construct.
_RETRY_HANDLERS = _retry_handlers()


def upload_png(
    png_bytes: bytes,
    *,
    token: Optional[str],
    channel: Optional[str],
    filename: str = "snapshot.png",
    initial_comment: Optional[str] = None,
) -> dict:
    if not token:
        raise SlackUploadError("SLACK_BOT_TOKEN is not configured.")
    if not channel:
        raise SlackUploadError("SLACK_CHANNEL_ID is not configured.")

    client = WebClient(token=token, retry_handlers=_RETRY_HANDLERS)
    try:
        response = client.files_upload_v2(
            channel=channel,
            content=png_bytes,
            filename=filename,
            initial_comment=initial_comment,
        )
    except SlackApiError as exc:
        detail = exc.response.get("error", str(exc)) if exc.response else str(exc)
        raise SlackUploadError(f"Slack upload failed: {detail}") from exc

    file_info = response.get("file") or (response.get("files") or [{}])[0]
    return {
        "ok": bool(response.get("ok", False)),
        "file_id": file_info.get("id"),
        "permalink": file_info.get("permalink"),
    }


def upload_pngs(
    images: list[tuple[bytes, str]],
    *,
    token: Optional[str],
    channel: Optional[str],
    initial_comment: Optional[str] = None,
) -> dict:
    """Upload several PNGs as a SINGLE Slack message (one post, many images).

    ``images`` is a list of ``(png_bytes, filename)`` in display order.
    files_upload_v2 with ``file_uploads`` + a single ``channel`` completes the
    upload once, so Slack renders them as one message / gallery.
    """
    if not token:
        raise SlackUploadError("SLACK_BOT_TOKEN is not configured.")
    if not channel:
        raise SlackUploadError("SLACK_CHANNEL_ID is not configured.")
    if not images:
        raise SlackUploadError("No images to upload.")

    client = WebClient(token=token, retry_handlers=_RETRY_HANDLERS)
    file_uploads = [
        {"content": png, "filename": filename, "title": filename}
        for png, filename in images
    ]
    try:
        response = client.files_upload_v2(
            channel=channel,
            file_uploads=file_uploads,
            initial_comment=initial_comment,
        )
    except SlackApiError as exc:
        detail = exc.response.get("error", str(exc)) if exc.response else str(exc)
        raise SlackUploadError(f"Slack upload failed: {detail}") from exc

    files = response.get("files") or (
        [response["file"]] if response.get("file") else []
    )
    return {
        "ok": bool(response.get("ok", False)),
        "count": len(files),
        "permalinks": [f.get("permalink") for f in files],
    }


def post_message(
    *,
    token: Optional[str],
    channel: Optional[str],
    text: str,
) -> dict:
    """Post a plain text message (chat.postMessage). Requires the chat:write scope."""
    if not token:
        raise SlackUploadError("SLACK_BOT_TOKEN is not configured.")
    if not channel:
        raise SlackUploadError("SLACK_CHANNEL_ID is not configured.")

    client = WebClient(token=token, retry_handlers=_RETRY_HANDLERS)
    try:
        response = client.chat_postMessage(channel=channel, text=text)
    except SlackApiError as exc:
        detail = exc.response.get("error", str(exc)) if exc.response else str(exc)
        raise SlackUploadError(f"Slack message failed: {detail}") from exc

    return {"ok": bool(response.get("ok", False)), "ts": response.get("ts")}
