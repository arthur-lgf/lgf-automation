# Approvals Analysis charts (`/approvalsanalysis`, weekly + monthly)

Bar charts of **approved amount** from the APPTRACK 3.0 **APPS** tab — WEEKLY
and MONTHLY totals — posted with the same dark LGF look as Sales Analysis.

```
/approvalsanalysis [weekly|monthly]        (default: weekly)   — on demand
scheduled: every Monday (weekly) + 1st of month (monthly) via cron-job.org
```

Same architecture as Sales Analysis: Slack slash command → Vercel listener →
GitHub `workflow_dispatch` → `scripts/approvals_analysis.py` renders + posts
the PNG(s).

---

## 1. Slash command (no new signing secret)
`/approvalsanalysis` reuses the **existing Approvals Slack app** — the Vercel
listener already verifies against `SLACK_SIGNING_SECRET_APPROVAL`.

1. https://api.slack.com/apps → your **Approvals** app → **Slash Commands → Create New Command**:
   | Command | Request URL | Usage hint |
   |---|---|---|
   | `/approvalsanalysis` | `https://lgf-automation.vercel.app/api/slack` | `[weekly\|monthly]` |
2. Save. `@lgf_approval_report` must already be a member of the channel
   (`/invite @lgf_approval_report`).

## 2. Scheduled posts (cron-job.org → GitHub Actions)
Cadences live in [cron-job.org](https://cron-job.org/) — no GitHub `schedule:`.
Clone an existing job per `docs/SCHEDULING.md` §§5–7 (same PAT, headers).

Both jobs:

| Field | Value |
|---|---|
| URL | `https://api.github.com/repos/arthur-lgf/lgf-automation/actions/workflows/approvals-analysis-scheduled.yml/dispatches` |
| Method | `POST` |
| Time zone | `America/New_York` |
| Headers | `Accept: application/vnd.github+json`; `Authorization: Bearer <PAT>`; `X-GitHub-Api-Version: 2022-11-28`; `Content-Type: application/json` |
| Notify on failure | On, threshold 2 |

| Job | Title | Schedule | Body |
|---|---|---|---|
| Weekly | `LGF Approvals Analysis - Monday 9:00 AM ET` | Days of week **Monday**; Hours **9**; Minutes **0**; Days of month Every | `{"ref":"main","inputs":{"kind":"weekly"}}` |
| Monthly | `LGF Approvals Analysis - 1st 9:00 AM ET` | Days of month **1**; Hours **9**; Minutes **0**; Days of week Every | `{"ref":"main","inputs":{"kind":"monthly"}}` |

A 204 from cron-job.org plus a GitHub Actions run **Triggered via API** is success.
The PNG posts to `APPROVALS_CHANNEL_ID` (fallback `SLACK_CHANNEL_ID`).

## 3. Push `main`
`approvals-analysis-ondemand.yml` and `approvals-analysis-scheduled.yml` must
exist on `main` before dispatch / cron-job.org will 204.

---

## Test it
- **On demand:** `/approvalsanalysis weekly` → ephemeral "Generating…", then the
  weekly bar chart in ~1–2 min (**Actions → Approvals Analysis (on demand)**).
  Try `/approvalsanalysis monthly`.
- **Scheduled dry run:** Actions → **Approvals Analysis (scheduled)** → Run
  workflow → kind `weekly` or `monthly`, gate `none`.
- **Local:** `uv run python scripts/approvals_analysis.py --kind both --output file`
  writes `approvals_analysis-weekly.png` / `approvals_analysis-monthly.png`.

## Notes
- **Look:** same renderer as Sales Analysis (`app/services/chart_renderer.py`).
- **Data:** APPS `Date Approved` + amount. Weekly = last 6 completed Mon–Sun
  weeks (`WE MM.DD`). Monthly = last 5 completed months + current month if it
  has approvals (`Apr 2026`).
- **Slack scopes:** the approvals bot token (`APPROVALS_SLACK_BOT_TOKEN`, with
  fallback `SLACK_BOT_TOKEN`) must have both `files:write` and `chat:write`.
  Empty-data text uses `chat.postMessage`.
- **No new secrets:** reuses `APPROVALS_SLACK_BOT_TOKEN` / `APPROVALS_CHANNEL_ID`
  (fallback `SLACK_BOT_TOKEN` / `SLACK_CHANNEL_ID`), `GOOGLE_SERVICE_ACCOUNT_JSON`,
  and the existing GitHub PAT / Slack signing secret.
