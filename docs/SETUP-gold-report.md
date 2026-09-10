# Monthly Gold Report (`/gold`, scheduled)

Ranked table from the Sales Report tab **V:Y**, same `dark_green` look as
`/sales monthly`.

```
/gold [monthly]        (default: monthly)   — on demand
scheduled: 12:30 PM ET and 5:00 PM ET daily via cron-job.org
```

Same pipeline as Sales: Slack slash command → Vercel listener → GitHub
`workflow_dispatch` → `scripts/snapshot.py` renders + posts the PNG.

---

## 1. Slash command
`/gold` goes in the **Sales Slack app** (same signing secret as `/sales`).

1. https://api.slack.com/apps → **Sales** app → **Slash Commands → Create New Command**:
   | Command | Request URL | Usage hint |
   |---|---|---|
   | `/gold` | `https://lgf-automation.vercel.app/api/slack` | `[monthly]` |
2. Save. Invite `@lgf_sales_report_bot` (`/invite @lgf_sales_report_bot`).

## 2. Scheduled posts (cron-job.org → GitHub Actions)
Clone an existing Snapshot job per `docs/SCHEDULING.md` §§5–7 (same PAT, headers).
Change only title, URL, and body.

| Field | Value |
|---|---|
| URL | `https://api.github.com/repos/arthur-lgf/lgf-automation/actions/workflows/gold-ondemand.yml/dispatches` |
| Method | `POST` |
| Time zone | `America/New_York` |
| Headers | `Accept: application/vnd.github+json`; `Authorization: Bearer <PAT>`; `X-GitHub-Api-Version: 2022-11-28`; `Content-Type: application/json` |
| Body | `{"ref":"main","inputs":{"report":"monthly"}}` |
| Notify on failure | On, threshold 2 |

| Job | Title | Schedule |
|---|---|---|
| Midday | `LGF Gold Report - 12:30 PM ET` | Days of month Every; Days of week Every; Hours **12**; Minutes **30** |
| Evening | `LGF Gold Report - 5:00 PM ET` | Days of month Every; Days of week Every; Hours **17**; Minutes **0** |

Scheduled posts go to `SLACK_CHANNEL_ID` (no channel input). `/gold` still posts
in the channel where it was invoked.

A 204 from cron-job.org plus a GitHub Actions run **Triggered via API** is success.

## 3. Push `main`
`gold-ondemand.yml` must exist on `main` before dispatch / cron-job.org will 204.
