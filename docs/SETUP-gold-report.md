# Monthly Gold Report (`/gold`, scheduled)

Ranked table from the Sales Report tab **V:Y**, gold theme (same gold as the
sheet block), not the green sales look. **Not part of Snapshot / Sales** — its
own workflow and cron-job.org jobs.

```
/gold [monthly]        (default: monthly)   — on demand
scheduled: 1st of each month, 9:00 AM ET via cron-job.org
```

On demand: Slack slash command → Vercel listener → `gold-ondemand.yml` →
`scripts/gold.py`. Scheduled: cron-job.org → the same `gold-ondemand.yml`.

---

## 1. Slash command (dedicated Gold Slack app)
`/gold` lives in Slack app [`A0C11GQ6ESE`](https://api.slack.com/apps/A0C11GQ6ESE)
— not the Sales app.

1. Open that app → **Slash Commands → Create New Command**:
   | Command | Request URL | Short description | Usage hint |
   |---|---|---|---|
   | `/gold` | `https://lgf-automation.vercel.app/api/slack` | Monthly Gold Report | `[monthly]` |
2. **OAuth & Permissions** — bot scopes `commands`, `chat:write`, `files:write`.
   **Install App** to the workspace. Copy the **Bot User OAuth Token** (`xoxb-…`).
3. GitHub → Settings → Secrets → Actions → `GOLD_SLACK_BOT_TOKEN` = that token.
4. Vercel env `SLACK_SIGNING_SECRET_GOLD` = **Basic Information → Signing Secret**.
5. In `C0ATW4FSK0X`: channel name → **Integrations → Add apps**
   → **LGF Gold Report**. `/invite` will not resolve the bot.

## 2. Scheduled posts (cron-job.org → Gold only)
Clone an existing job at [console.cron-job.org/jobs](https://console.cron-job.org/jobs)
(same PAT, headers as Snapshot). Point it at **Gold**, not `snapshot.yml`.

| Field | Value |
|---|---|
| URL | `https://api.github.com/repos/arthur-lgf/lgf-automation/actions/workflows/gold-ondemand.yml/dispatches` |
| Method | `POST` |
| Time zone | `America/New_York` |
| Headers | same as Snapshot (`Accept`, `Authorization: Bearer <PAT>`, `X-GitHub-Api-Version`, `Content-Type`) |
| Body | `{"ref":"main","inputs":{"report":"monthly"}}` |

| Job | Title | Schedule |
|---|---|---|
| Monthly | `LGF Gold Report - 1st 9:00 AM ET` | Days of month **1**; Hours **9**; Minutes **0**; Days of week Every |

Scheduled posts go to `C0ATW4FSK0X`. `/gold` posts in the channel where it
was invoked, plus `C0ATW4FSK0X` if that is different.
`C0BFN82DDLN` is test-only — leave `GOLD_EXTRA_CHANNEL_ID` commented.

A GitHub Actions run **Gold Report (on demand)** **Triggered via API** is success.
Snapshot stays Daily + Monthly Sales only.

## 3. Local run
Same as sales (`scripts/snapshot.py`), but Gold only:

```bash
uv run python scripts/gold.py --output file --out-path gold.png
```

`--output slack` posts with `GOLD_SLACK_BOT_TOKEN` (fallback `SLACK_BOT_TOKEN`)
to `C0ATW4FSK0X`.

## 4. Push `main`
`gold-ondemand.yml` and `scripts/gold.py` must exist on `main` before the Gold cron jobs will 204.
