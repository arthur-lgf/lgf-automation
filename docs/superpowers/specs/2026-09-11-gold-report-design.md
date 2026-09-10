# Monthly Gold Report

Date: 2026-09-11

On-demand ranked-table PNG of the Gold Report block on the Sales Report tab,
posted to Slack. Same look and pipeline as `/sales monthly`.

## Goal

- On demand: `/gold` or `/gold monthly` posts one table PNG in the channel the
  command was run from.
- Scheduled: existing Snapshot cron-job.org jobs at **12:30 PM ET** and
  **5:00 PM ET** daily (`snapshot.yml` matrix includes Monthly Gold Report).
  Posts to `SLACK_CHANNEL_ID` and also to `C0BFN82DDLN` using the sales bot.
- Source is columns **V–Y** on the Sales Report tab (gid `170384010`) of
  spreadsheet `12glaANnP2BsQfH_kHfRlzA40JdWAU-PJgDT-56yRV8k`.
- Visual match: `dark_green` ranked table (same as `/sales`), title
  **Monthly Gold Report**.

## Non-goals

- No daily Gold block, no `/gold daily`.
- Do not change `/sales`, `/skools`, snapshot.yml, or `scripts/snapshot.py`.
- Scheduling uses the existing Snapshot cron-job.org jobs (`snapshot.yml` matrix).
- No new Slack app, signing secret, bot, or GitHub Actions secret.

## Architecture

```
/gold monthly
        → Vercel /api/slack  (existing listener, sales signing secret)
        → GitHub gold-ondemand.yml
        → scripts/snapshot.py  (unchanged)
        → Slack PNG in the invoking channel

cron-job.org Snapshot jobs (12:30 PM ET / 5:00 PM ET daily)
        → GitHub snapshot.yml (Monthly Gold Report matrix)
        → scripts/snapshot.py
        → Slack PNG in SLACK_CHANNEL_ID and C0BFN82DDLN
```

## Sheet

| Field | Value |
|---|---|
| Spreadsheet | `12glaANnP2BsQfH_kHfRlzA40JdWAU-PJgDT-56yRV8k` |
| GID | `170384010` (Sales Report tab) |
| Range | `V1:Y50` |
| `ONLY_RANKED` | `1` |
| Theme | `dark_green` |
| Title | Monthly Gold Report |

Row 50 matches Daily/Monthly Sales and Skool blocks so totals below the ranked
rows are included.

## Slack command

- Command: `/gold`
- Valid arg: `monthly` (default when omitted)
- Invalid arg (including `daily`): usage
  ``Usage: `/gold [monthly]` (default: monthly)``
- Workflow: `gold-ondemand.yml`
- Inputs: `{"report": "monthly", "channel": <invoking channel>}`
- Ack: ephemeral “Generating the *monthly gold* report…”
- Lives in the **Sales Slack app** (same Request URL as `/sales`).
- Posts with the existing sales bot (`SLACK_BOT_TOKEN` / `@lgf_sales_report_bot`).

Empty ranked data uses the existing snapshot.py text
“No sales to report for Monthly Gold Report …”.

## Files

- Create: `.github/workflows/gold-ondemand.yml` (clone of `sales-ondemand.yml`)
- Modify: `app/services/slack_commands.py`, `tests/test_slack_commands.py`,
  `docs/SETUP-slack-commands.md`

## Operator step (not code)

Create `/gold` at https://api.slack.com/apps → Sales app → Slash Commands.

| Command | Request URL | Usage hint |
|---|---|---|
| `/gold` | `https://lgf-automation.vercel.app/api/slack` | `[monthly]` |
