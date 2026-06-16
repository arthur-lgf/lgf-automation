from __future__ import annotations

from typing import Optional

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


class SlackUploadError(RuntimeError):
    pass


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

    client = WebClient(token=token)
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

    client = WebClient(token=token)
    try:
        response = client.chat_postMessage(channel=channel, text=text)
    except SlackApiError as exc:
        detail = exc.response.get("error", str(exc)) if exc.response else str(exc)
        raise SlackUploadError(f"Slack message failed: {detail}") from exc

    return {"ok": bool(response.get("ok", False)), "ts": response.get("ts")}
