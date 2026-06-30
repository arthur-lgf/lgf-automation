"""Vercel serverless function: the Slack slash-command endpoint (/api/slack).

A thin shell over app.services.slack_commands.handle_slash_request — it reads the
raw POST body (needed for signature verification) and the Slack headers, hands
them to the tested pure-logic layer, and writes back the ephemeral JSON reply.

Config via Vercel env vars:
  SLACK_SIGNING_SECRET_APPROVAL  signing secret of the Slack app hosting /approvals
  SLACK_SIGNING_SECRET_SALES     signing secret of the Slack app hosting /sales
  SLACK_SIGNING_SECRET           legacy single-app secret (optional fallback)
  GITHUB_TOKEN          fine-grained PAT with actions:write on the repo
  GITHUB_REPO           "owner/repo" to dispatch workflows in
  GITHUB_REF_NAME       branch to run workflows on (optional, default "main")

A request is accepted if it verifies against ANY of the configured signing
secrets, so /approvals and /sales can live in two separate Slack apps.
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler

# Ensure the repo root (parent of api/) is importable so `app.*` resolves
# regardless of the function's working directory on Vercel.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.slack_commands import handle_slash_request  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length) if length else b""
        result = handle_slash_request(
            raw_body=raw,
            headers={k: v for k, v in self.headers.items()},
            signing_secret=[
                os.environ.get("SLACK_SIGNING_SECRET_APPROVAL", ""),
                os.environ.get("SLACK_SIGNING_SECRET_SALES", ""),
                os.environ.get("SLACK_SIGNING_SECRET", ""),  # legacy single-app
            ],
            github_token=os.environ.get("GITHUB_TOKEN", ""),
            repo=os.environ.get("GITHUB_REPO", ""),
            ref=os.environ.get("GITHUB_REF_NAME", "main"),
        )
        self._write(result.status, json.dumps(result.body).encode(), "application/json")

    def do_GET(self):
        self._write(200, b"LGF Slack commands endpoint is live. POST slash commands here.", "text/plain")

    def _write(self, status: int, body: bytes, content_type: str):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
