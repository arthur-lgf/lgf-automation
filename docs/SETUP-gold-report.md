# Monthly Gold Report (`/gold`, scheduled)

Ranked table from the Sales Report tab **V:Y**, same `dark_green` look as
`/sales monthly`. **Not part of Snapshot / Sales** — its own workflow and
cron-job.org jobs.

```
/gold [monthly]        (default: monthly)   — on demand
scheduled: dedicated cron-job.org jobs at 12:30 PM ET and 5:00 PM ET
```

On demand: Slack slash command → Vercel listener → `gold-ondemand.yml` →
`scripts/snapshot.py`. Scheduled: cron-job.org → the same `gold-ondemand.yml`.

---

## 1. Slash command
`/gold` goes in the **Sales Slack app** (same signing secret as `/sales`).

1. https://api.slack.com/apps → **Sales** app → **Slash Commands → Create New Command**:
   | Command | Request URL | Usage hint |
   |---|---|---|
   | `/gold` | `https://lgf-automation.vercel.app/api/slack` | `[monthly]` |
2. Save. Invite `@lgf_sales_report_bot` in the sales channel and in
   `C0BFN82DDLN` (`/invite @lgf_sales_report_bot`).

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

Scheduled posts go to `SLACK_CHANNEL_ID` **and** `C0BFN82DDLN`. `/gold` posts in
the channel where it was invoked, plus `C0BFN82DDLN` if that is a different
channel.

A GitHub Actions run **Gold Report (on demand)** **Triggered via API** is success.
Snapshot stays Daily + Monthly Sales only.

## 3. Push `main`
`gold-ondemand.yml` must exist on `main` before the Gold cron jobs will 204.
