# Monthly Gold Report

Date: 2026-09-11

On-demand ranked-table PNG of the Gold Report block on the Sales Report tab,
posted to Slack. Same look and pipeline as `/sales monthly`.

## Goal

- On demand: `/gold` or `/gold monthly` posts one table PNG in the channel the
  command was run from.
- Scheduled via dedicated [cron-job.org](https://cron-job.org/) jobs at
  **12:30 PM ET** and **5:00 PM ET** daily hitting `gold-ondemand.yml` (not
  `snapshot.yml`). Posts to Gold channels `C0ATW4FSK0X` and `C0BFN82DDLN`.
- Source is columns **V–Y** on the Sales Report tab (gid `170384010`) of
  spreadsheet `12glaANnP2BsQfH_kHfRlzA40JdWAU-PJgDT-56yRV8k`.
- Visual match: `gold` ranked table (sheet Gold block, not sales green), title
  **Monthly Gold Report**.

## Non-goals

- No daily Gold block, no `/gold daily`.
- Do not change `/sales`, `/skools`, snapshot.yml, or `scripts/snapshot.py`.
- Scheduling is dedicated cron-job.org jobs hitting `gold-ondemand.yml`.
- No new Slack app, signing secret, bot, or GitHub Actions secret.

## Architecture

```
/gold monthly
        → Vercel /api/slack  (existing listener, sales signing secret)
        → GitHub gold-ondemand.yml
        → scripts/gold.py
        → Slack PNG in the invoking channel (+ C0ATW4FSK0X, C0BFN82DDLN)

cron-job.org Gold jobs (12:30 PM ET / 5:00 PM ET daily)
        → GitHub gold-ondemand.yml
        → scripts/gold.py
        → Slack PNG in C0ATW4FSK0X and C0BFN82DDLN
```

## Sheet

| Field | Value |
|---|---|
| Spreadsheet | `12glaANnP2BsQfH_kHfRlzA40JdWAU-PJgDT-56yRV8k` |
| GID | `170384010` (Sales Report tab) |
| Range | `V1:Y50` |
| `ONLY_RANKED` | `1` |
| Theme | `gold` |
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
- Lives in the **Gold Slack app** [`A0C11GQ6ESE`](https://api.slack.com/apps/A0C11GQ6ESE)
  (`SLACK_SIGNING_SECRET_GOLD`).
- Posts with `GOLD_SLACK_BOT_TOKEN` (fallback `SLACK_BOT_TOKEN`).

Empty ranked data uses `scripts/gold.py` text
“No gold to report for Monthly Gold Report …”.

## Files

- Create: `.github/workflows/gold-ondemand.yml`, `scripts/gold.py`
- Modify: `app/services/slack_commands.py`, `tests/test_slack_commands.py`,
  `docs/SETUP-slack-commands.md`

## Operator step (not code)

Create `/gold` at https://api.slack.com/apps/A0C11GQ6ESE → Slash Commands.

| Command | Request URL | Short description | Usage hint |
|---|---|---|---|
| `/gold` | `https://lgf-automation.vercel.app/api/slack` | Monthly Gold Report | `[monthly]` |
