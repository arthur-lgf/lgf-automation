# Monthly Gold Report (`/gold`, scheduled)

Ranked table from the Sales Report tab **V:Y**, gold theme (same gold as the
sheet block), not the green sales look. **Not part of Snapshot / Sales** — its
own workflow and cron-job.org jobs.

```
/gold [monthly]        (default: monthly)   — on demand
scheduled: dedicated cron-job.org jobs at 12:30 PM ET and 5:00 PM ET
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
5. In `C0ATW4FSK0X` and `C0BFN82DDLN`: channel name → **Integrations → Add apps**
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

| Title | Hours | Minutes |
|---|---|---|
| `LGF Gold Report - 12:30 PM ET` | 12 | 30 |
| `LGF Gold Report - 5:00 PM ET` | 17 | 0 |

Scheduled posts go to `C0ATW4FSK0X` and `C0BFN82DDLN`. `/gold` posts in the
channel where it was invoked, plus those two if they are different.

A GitHub Actions run **Gold Report (on demand)** **Triggered via API** is success.
Snapshot stays Daily + Monthly Sales only.

## 3. Local run
Same as sales (`scripts/snapshot.py`), but Gold only:

```bash
uv run python scripts/gold.py --output file --out-path gold.png
```

`--output slack` posts with `GOLD_SLACK_BOT_TOKEN` (fallback `SLACK_BOT_TOKEN`)
to `C0ATW4FSK0X` and `C0BFN82DDLN`.

## 4. Push `main`
`gold-ondemand.yml` and `scripts/gold.py` must exist on `main` before the Gold cron jobs will 204.
