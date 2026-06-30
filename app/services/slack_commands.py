"""Pure logic for the Slack slash-command -> GitHub-workflow listener.

Deliberately STANDARD-LIBRARY ONLY (hmac/hashlib/json/time/urllib) so the Vercel
function that imports it stays tiny and cold-starts fast — it must NOT pull in
this repo's heavy report deps (Playwright, Google). The Vercel handler in
``api/slack.py`` is a thin shell over ``handle_slash_request`` here.

Flow: verify the Slack signing-secret signature (with a replay-age guard) ->
parse ``/approvals``/``/sales`` + period -> fire the matching GitHub workflow via
``workflow_dispatch`` -> reply with an ephemeral "generating…" message. The
report itself is produced and posted by the workflow (reusing all existing code).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

_SIG_VERSION = "v0"
MAX_REQUEST_AGE_SECONDS = 300  # Slack replay-protection window.

_APPROVALS_PERIODS = ("today", "yesterday", "last-week", "last-month")
_SALES_REPORTS = ("daily", "monthly")

_APPROVALS_LABELS = {
    "today": "today's approvals",
    "yesterday": "yesterday's approvals",
    "last-week": "weekly approvals",
    "last-month": "monthly approvals",
}
_SALES_LABELS = {"daily": "daily sales", "monthly": "monthly sales"}


class CommandError(ValueError):
    """Bad/missing command args. ``str(err)`` is a Slack-ready usage message."""


@dataclass
class CommandResult:
    workflow: str  # workflow filename to dispatch, e.g. "approvals.yml"
    inputs: dict  # workflow_dispatch inputs (all string values)
    report_label: str  # human label for the ack message


@dataclass
class HandlerResponse:
    status: int
    body: dict  # JSON body returned to Slack (an ephemeral message)


def verify_signature(
    *,
    signing_secret: Optional[str],
    timestamp: Optional[str],
    signature: Optional[str],
    body,
    now: Optional[float] = None,
    max_age: int = MAX_REQUEST_AGE_SECONDS,
) -> bool:
    """True iff ``signature`` is a valid Slack v0 signature for ``body`` and the
    request is within ``max_age`` seconds (replay guard). See Slack's
    'Verifying requests' docs."""
    if not signing_secret or not timestamp or not signature:
        return False
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    now = time.time() if now is None else now
    if abs(now - ts) > max_age:
        return False
    if isinstance(body, bytes):
        body = body.decode("utf-8")
    base = f"{_SIG_VERSION}:{timestamp}:{body}".encode()
    digest = hmac.new(signing_secret.encode(), base, hashlib.sha256).hexdigest()
    expected = f"{_SIG_VERSION}={digest}"
    return hmac.compare_digest(expected, signature)


def _normalize_secrets(signing_secret) -> list:
    """Coerce ``signing_secret`` (a single secret or an iterable of them) into a
    list of usable secrets. Blanks are dropped (unset env vars arrive as "") and
    surrounding whitespace is stripped (a trailing newline is a common copy-paste
    artifact that would otherwise silently fail every request)."""
    if signing_secret is None:
        return []
    if isinstance(signing_secret, bytes):
        signing_secret = signing_secret.decode("utf-8")
    candidates = [signing_secret] if isinstance(signing_secret, str) else list(signing_secret)
    out = []
    for cand in candidates:
        if cand is None:
            continue
        if isinstance(cand, bytes):
            cand = cand.decode("utf-8")
        cand = cand.strip()
        if cand:
            out.append(cand)
    return out


def _usage_approvals() -> str:
    return "Usage: `/approvals [today|yesterday|last-week|last-month]` (default: today)"


def _usage_sales() -> str:
    return "Usage: `/sales [daily|monthly]` (default: daily)"


def parse_command(command: str, text: str, channel_id: str) -> CommandResult:
    """Map a slash command + its first arg to the workflow to dispatch.

    Raises ``CommandError`` (with a usage message) on an unknown command or an
    invalid period/report arg."""
    cmd = (command or "").strip().lower().lstrip("/")
    parts = (text or "").strip().lower().split()
    arg = parts[0] if parts else ""

    if cmd == "approvals":
        period = arg or "today"
        if period not in _APPROVALS_PERIODS:
            raise CommandError(_usage_approvals())
        return CommandResult(
            "approvals.yml", {"period": period, "channel": channel_id}, _APPROVALS_LABELS[period]
        )
    if cmd == "sales":
        report = arg or "daily"
        if report not in _SALES_REPORTS:
            raise CommandError(_usage_sales())
        return CommandResult(
            "sales-ondemand.yml", {"report": report, "channel": channel_id}, _SALES_LABELS[report]
        )
    raise CommandError(f"Unknown command `/{cmd}`. Try `/approvals` or `/sales`.")


def dispatch_workflow(
    *,
    repo: str,
    workflow: str,
    ref: str,
    inputs: dict,
    token: str,
    opener: Callable = urllib.request.urlopen,
) -> int:
    """POST a ``workflow_dispatch`` to GitHub Actions. Returns the HTTP status
    (204 on success). ``opener`` is injectable for tests."""
    url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow}/dispatches"
    payload = json.dumps({"ref": ref, "inputs": inputs}).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "lgf-slack-commands",
        },
    )
    resp = opener(req)
    return getattr(resp, "status", None) or resp.getcode()


def _header(headers: dict, name: str) -> Optional[str]:
    target = name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return value
    return None


def _ephemeral(text: str) -> dict:
    return {"response_type": "ephemeral", "text": text}


def handle_slash_request(
    *,
    raw_body,
    headers: dict,
    signing_secret,  # a single secret (str) or an iterable of them (one per app)
    github_token: str,
    repo: str,
    ref: str = "main",
    now: Optional[float] = None,
    dispatcher: Optional[Callable] = None,
) -> HandlerResponse:
    """End-to-end handling of one Slack slash-command POST: verify -> parse ->
    dispatch -> ephemeral reply. Never raises; every failure becomes a response."""
    signature = _header(headers, "X-Slack-Signature")
    timestamp = _header(headers, "X-Slack-Request-Timestamp")
    # ``signing_secret`` may be a single secret or several (one per Slack app, when
    # /approvals and /sales live in different apps). The request is authentic if it
    # verifies against ANY configured secret.
    secrets = _normalize_secrets(signing_secret)
    verified = any(
        verify_signature(
            signing_secret=secret, timestamp=timestamp, signature=signature,
            body=raw_body, now=now,
        )
        for secret in secrets
    )
    if not verified:
        return HandlerResponse(401, _ephemeral("Signature verification failed."))

    decoded = raw_body.decode("utf-8") if isinstance(raw_body, bytes) else raw_body
    form = urllib.parse.parse_qs(decoded)

    def field(name: str) -> str:
        values = form.get(name) or [""]
        return values[0]

    try:
        result = parse_command(field("command"), field("text"), field("channel_id"))
    except CommandError as exc:
        return HandlerResponse(200, _ephemeral(str(exc)))

    dispatch = dispatcher or dispatch_workflow
    try:
        status = dispatch(
            repo=repo, workflow=result.workflow, ref=ref,
            inputs=result.inputs, token=github_token,
        )
    except Exception as exc:  # network/HTTP error -> tell the user, don't 500.
        return HandlerResponse(200, _ephemeral(f"Couldn't start the report: {exc}"))

    if status not in (200, 201, 204):
        return HandlerResponse(
            200, _ephemeral(f"Couldn't start the report (GitHub returned {status}).")
        )
    return HandlerResponse(
        200,
        _ephemeral(
            f":bar_chart: Generating the *{result.report_label}* report — "
            "it'll post in this channel shortly."
        ),
    )
