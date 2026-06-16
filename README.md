# lgf-automation

FastAPI service that turns a Google Sheets range into a styled PNG snapshot and either streams it back or uploads it to Slack. Built with async Playwright for rendering and the Google Sheets API for private-sheet access.

## Endpoint

```
GET /snapshots/google-sheet
```

| Query param      | Required | Notes                                                              |
|------------------|----------|--------------------------------------------------------------------|
| `spreadsheet_id` | yes      | Google Sheets ID                                                   |
| `range`          | yes      | A1 notation, e.g. `B1:J25`                                         |
| `gid` or `sheet_name` | yes (one) | Tab numeric id, or tab name                                 |
| `theme`          | no       | CSS theme name in [app/themes/](app/themes/). Default `dark_gold`. |
| `output`         | no       | `image` (default) or `slack`                                       |
| `source`         | no       | `api` (default, uses service account) or `html` (public sheets)    |
| `title`          | no       | Used as `<title>` and Slack initial comment                        |

## Approvals report (daily, cron-triggered)

```
GET /reports/approvals
```

Posts a green "APPROVALS REPORT" PNG of every deal **approved today** in the
**APPTRACK 3.0** workbook (tab `APPS`). It reuses the same renderer/screenshot/Slack
pipeline as `/snapshots/google-sheet` — it just filters the sheet to today's
`Date Approved` rows, ranks them, and totals the amount.

| Query param | Required | Notes |
|-------------|----------|-------|
| `output`    | no | `slack` (default, uploads the PNG) or `image` (returns the PNG) |
| `date`      | no | `M/D/YYYY` override; default = today in `REPORT_TZ`. Use it to dry-run a past day |
| `channel`   | no | Override `APPROVALS_CHANNEL_ID` for one call |
| `spreadsheet_id` / `gid` / `sheet_name` / `range` / `theme` | no | Default from env; rarely needed |

If no deals were approved that day it posts nothing (the endpoint returns
`{"posted": false, ...}`; the scheduled job logs it and exits 0).

**One-time prerequisites**

1. **Share the APPTRACK 3.0 sheet** with the service account
   `lgf-bot@lgf-automation.iam.gserviceaccount.com` (Viewer).
2. **Pick the Slack channel** and invite the LGF bot. To post somewhere other
   than `SLACK_CHANNEL_ID`, set `APPROVALS_CHANNEL_ID` (a GitHub Actions secret
   for the scheduled run, or in `.env` for local). If unset it falls back to
   `SLACK_CHANNEL_ID`.

### Production: scheduled via GitHub Actions (same as the snapshot reports)

There is **no hosted server** — the report runs serverless. [`scripts/approvals.py`](scripts/approvals.py)
(same logic as the endpoint) runs inside [`.github/workflows/approvals.yml`](.github/workflows/approvals.yml)
(`workflow_dispatch`), and **cron-job.org** calls its dispatch URL daily at
11:00 AM `America/New_York`. Follow [docs/SCHEDULING.md](docs/SCHEDULING.md) and
add **one** cron-job.org job (clone an existing one and change only these):

- **URL:** `https://api.github.com/repos/arthur-lgf/lgf-automation/actions/workflows/approvals.yml/dispatches`
- **Schedule:** Hour `11`, Minute `0`, Time zone `America/New_York`
- Method `POST`, body `{"ref":"main"}`, same `Authorization: Bearer <PAT>` headers as the snapshot jobs.

Uses the existing `SLACK_BOT_TOKEN`, `SLACK_CHANNEL_ID`, and
`GOOGLE_SERVICE_ACCOUNT_JSON` Actions secrets. Trigger it by hand anytime via
**Actions → Approvals Report → Run workflow** (optionally pass a `date`).

### Local / manual run

```bash
# CLI (what the workflow runs) — write a PNG without posting:
uv run python scripts/approvals.py --output file --out-path approvals.png --date 6/15/2026
# CLI — post to Slack:
uv run python scripts/approvals.py --output slack

# Or via the HTTP endpoint (uvicorn running locally):
curl -s "http://localhost:8000/reports/approvals?output=image&date=6/15/2026" -o approvals.png
curl -fsS --max-time 120 "http://localhost:8000/reports/approvals?output=slack"
```

## Local setup (uv)

```bash
cd lgf-automation
uv sync
uv run playwright install chromium --with-deps
cp .env.example .env   # fill in SLACK_BOT_TOKEN, SLACK_CHANNEL_ID, etc.
uv run uvicorn app.main:app --reload
```

Service listens on `http://localhost:8000`. Swagger UI at `/docs`.

## Docker setup

```bash
docker compose up --build
```

Drop your Google service-account JSON at `secrets/service-account.json` — the compose file mounts `./secrets` read-only and points `GOOGLE_APPLICATION_CREDENTIALS` at it.

## Environment variables

| Var                              | Purpose                                                   |
|----------------------------------|-----------------------------------------------------------|
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to the Google service-account JSON                   |
| `SLACK_BOT_TOKEN`                | Bot token (`xoxb-...`) with `files:write`, `chat:write`   |
| `SLACK_CHANNEL_ID`               | Target channel ID (e.g. `C0123ABCDEF`), not the name      |
| `DEFAULT_SPREADSHEET_ID`         | (optional) Smoke-test defaults                            |
| `DEFAULT_GID` / `DEFAULT_RANGE`  | (optional) Smoke-test defaults                            |
| `VIEWPORT_WIDTH` / `VIEWPORT_HEIGHT` | Playwright viewport (default 1400×900)                |
| `APPROVALS_CHANNEL_ID`           | Channel for the approvals report (bot must be a member)   |
| `APPROVALS_SPREADSHEET_ID` / `APPROVALS_GID` / `APPROVALS_RANGE` | APPTRACK 3.0 source (defaults baked in) |
| `REPORT_TZ`                      | TZ for "today" on `/reports/approvals` (default `America/New_York`) |
| `APPROVALS_COLS`                 | 0-based column indices `date_approved,client,bank,amount,invoice_sent,rep` |

## Google service-account setup

1. In Google Cloud Console, enable the **Google Sheets API** for a project.
2. Create a service account, download a JSON key, save it to `secrets/service-account.json`.
3. Open the target Google Sheet and **share it with the service account's email** (Viewer is enough).

## Example curl

Stream a PNG to a file:

```bash
curl -s "http://localhost:8000/snapshots/google-sheet?spreadsheet_id=12glaANnP2BsQfH_kHfRlzA40JdWAU-PJgDT-56yRV8k&gid=170384010&range=B1:J25" \
  -o snapshot.png
```

Upload to Slack:

```bash
curl -s "http://localhost:8000/snapshots/google-sheet?spreadsheet_id=12glaANnP2BsQfH_kHfRlzA40JdWAU-PJgDT-56yRV8k&gid=170384010&range=B1:J25&output=slack&title=Daily%20Report"
```

Use the HTML fallback (works only when the sheet is "Anyone with the link"):

```bash
curl -s "http://localhost:8000/snapshots/google-sheet?spreadsheet_id=...&gid=170384010&range=B1:J25&source=html" -o snapshot.png
```

## Tests

```bash
uv run pytest -q
```

Route tests patch the sheets/screenshot/slack services so they don't need network or a browser.

## Project layout

```
app/
  main.py              FastAPI app factory
  config.py            pydantic-settings env loader
  routers/snapshots.py GET /snapshots/google-sheet
  routers/reports.py   GET /reports/approvals (daily approvals report)
  services/
    sheets.py          Google Sheets API + HTML fallback
    renderer.py        values -> HTML table via Jinja2
    approvals.py       filter today's approvals -> report matrix
    screenshot.py      async Playwright capture
    slack.py           slack_sdk files_upload_v2
  templates/report.html.j2
  themes/dark_gold.css
tests/                 pytest suite
Dockerfile             Playwright-Python base image
docker-compose.yml     Local dev convenience
```

## Notes

- Slack uploads use `slack_sdk.WebClient.files_upload_v2`, which wraps the new external-upload flow. The legacy `files.upload` endpoint was deprecated in March 2025 and is not supported here.
- Cell values matching `^-?[\d,.\s$€£%()]+$` get a `.amount` class for centered alignment. Tweak `_AMOUNT_RE` in [app/services/renderer.py](app/services/renderer.py) if your data needs different rules.
- Add new themes by dropping a `<name>.css` file into [app/themes/](app/themes/) and passing `?theme=<name>`.
