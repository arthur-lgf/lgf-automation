# Monthly Gold Report (`/gold`, scheduled)

Ranked table from the Sales Report tab **V:Y**, same `dark_green` look as
`/sales monthly`.

```
/gold [monthly]        (default: monthly)   — on demand
scheduled: existing Snapshot cron-job.org jobs at 12:30 PM ET and 5:00 PM ET
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
2. Save. Invite `@lgf_sales_report_bot` in the sales channel and in
   `C0BFN82DDLN` (`/invite @lgf_sales_report_bot`).

## 2. Scheduled posts
Gold rides the **existing** Snapshot cron-job.org jobs (`docs/SCHEDULING.md`):
**12:30 PM ET** and **5:00 PM ET** daily. No new console job. Those jobs already
dispatch `snapshot.yml`; Gold is a third matrix report (`V1:Y50`).

Scheduled posts go to `SLACK_CHANNEL_ID` **and** `C0BFN82DDLN`. Invite
`@lgf_sales_report_bot` in both. `/gold` posts in the channel where it was
invoked, plus `C0BFN82DDLN` if that is a different channel.

A GitHub Actions run **Snapshot → Monthly Gold Report** is success.

## 3. Push `main`
`snapshot.yml` (Gold matrix row) and `gold-ondemand.yml` must be on `main`
before the next 12:30 / 5:00 PM ET Snapshot fire.
