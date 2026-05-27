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
  services/
    sheets.py          Google Sheets API + HTML fallback
    renderer.py        values -> HTML table via Jinja2
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
