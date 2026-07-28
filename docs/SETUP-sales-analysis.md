# Sales Analysis charts (`/salesanalysis`, weekly + monthly)

Re-rendered bar charts of the **Analysis tab** (`gid=1867438179`) of the sales
workbook — WEEKLY and MONTHLY sales totals — posted to the sales channel. The
charts are drawn from the sheet data via the service account (the embedded Google
charts can't be screenshotted on a runner), styled in the dark LGF theme.

```
/salesanalysis [weekly|monthly]        (default: weekly)   — on demand
scheduled: first Monday of the month + last day of the month (both charts)
```

Same architecture as the other reports: Slack slash command → Vercel listener →
GitHub `workflow_dispatch` → `scripts/sales_analysis.py` renders + posts the PNG(s).

---

## 1. Slash command (no new signing secret)
`/salesanalysis` reuses the **existing Sales Slack app** — the Vercel listener
already verifies against `SLACK_SIGNING_SECRET_SALES`, so nothing changes in Vercel.

1. https://api.slack.com/apps → your **Sales** app → **Slash Commands → Create New Command**:
   | Command | Request URL | Usage hint |
   |---|---|---|
   | `/salesanalysis` | `https://lgf-automation.vercel.app/api/slack` | `[weekly\|monthly]` |
2. Save. Make sure the sales report bot (`SLACK_BOT_TOKEN`) is already a member of
   the channel you'll run it in (it is, for the sales report).

## 2. Scheduled posts (cron-job.org → GitHub Actions)
Both cadences are expressed directly in cron-job.org — no script gating needed.

Create **two** cron-job.org jobs (clone an existing one per `docs/SCHEDULING.md` §6–7),
timezone **America/New_York**, both pointed at:
```
https://api.github.com/repos/arthur-lgf/lgf-automation/actions/workflows/sales-analysis-scheduled.yml/dispatches
```
Headers: `Accept: application/vnd.github+json`, `Authorization: Bearer <PAT>`,
`X-GitHub-Api-Version: 2022-11-28`, `Content-Type: application/json`.

| Job | Schedule | Request body |
|---|---|---|
| Weekly | every **Monday**, ~9:00 AM ET | `{"ref":"main","inputs":{"kind":"weekly"}}` |
| Monthly | **1st of each month**, ~9:00 AM ET | `{"ref":"main","inputs":{"kind":"monthly"}}` |

The Monday job posts the weekly chart; the 1st-of-month job posts the monthly chart.

## 3. Push `main`
The two new workflows (`sales-analysis-ondemand.yml`, `sales-analysis-scheduled.yml`)
must exist on `main` for dispatch to find them. Merge + `git push origin main`.

---

## Test it
- **On demand:** in the sales channel, `/salesanalysis weekly` → instant
  "📊 Generating…" ephemeral, then the weekly bar chart posts ~1–2 min later
  (watch **GitHub → Actions → Sales Analysis (on demand)**). Try `/salesanalysis monthly`.
- **Scheduled dry run:** GitHub → Actions → **Sales Analysis (scheduled)** → Run
  workflow → gate `none` → confirms both charts post regardless of date.
- **Local:** `uv run python scripts/sales_analysis.py --kind both --output file`
  writes `sales_analysis-weekly.png` / `sales_analysis-monthly.png` for a dry look.

## Notes
- **Look:** a re-render in the dark LGF theme (black/gold, colored bars), not the
  light Google chart. To restyle, edit `app/services/chart_renderer.py` (palette +
  the card/title styles) — one file, no wiring changes.
- **Data window:** a week/month appears once its Start Date has passed, so the
  current in-progress period shows as a partial bar and future `$0.00` placeholders
  are hidden. Configured via the Analysis-tab layout in `app/services/chart_data.py`.
- **No new secrets:** reuses `SLACK_BOT_TOKEN`, `SLACK_CHANNEL_ID`,
  `GOOGLE_SERVICE_ACCOUNT_JSON`, and the existing GitHub PAT / Slack signing secret.
