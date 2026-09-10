# Approvals Analysis charts

Date: 2026-09-11

Weekly and monthly bar charts of **approved amount**, matching the look of the
existing Sales Analysis charts, posted to Slack. The current `/approvals` tables
and leaderboards stay unchanged.

## Goal

- On demand: `/approvalsanalysis [weekly|monthly]` (default `weekly`) posts one
  bar-chart PNG in the channel the command was run from.
- Scheduled via [cron-job.org](https://cron-job.org/): Monday posts the weekly
  chart; the 1st of each month posts the monthly chart. Both go to
  `APPROVALS_CHANNEL_ID` using the existing approvals bot.
- Visual match: same dark LGF card, gold title, colored bars, money labels as
  Sales Analysis (`WEEKLY SALES ANALYSIS` / `MONTHLY SALES ANALYSIS` screenshots).
  Titles are `WEEKLY APPROVALS ANALYSIS` and `MONTHLY APPROVALS ANALYSIS`.

## Non-goals

- Do not change `/approvals`, the daily/yesterday/weekly/monthly table reports,
  or APPTRACK sheet layout.
- Do not add an Analysis tab in Google Sheets.
- Do not share a CLI with `scripts/sales_analysis.py`.
- No new Slack apps, signing secrets, or GitHub Actions secrets.

## Architecture

Same serverless pattern as Sales Analysis. Nothing renders inside Vercel.

```
/approvalsanalysis weekly|monthly
        → Vercel /api/slack  (existing listener)
        → GitHub approvals-analysis-ondemand.yml
        → scripts/approvals_analysis.py
        → Slack PNG in the invoking channel

cron-job.org (Monday / 1st of month)
        → GitHub approvals-analysis-scheduled.yml
        → same script
        → Slack PNG in APPROVALS_CHANNEL_ID
```

Data path: Google Sheets APPS tab → aggregate series →
`app.services.chart_renderer.render_bar_chart` → Playwright screenshot → Slack
upload. Reuse `fetch_values`, `snapshot_html`, `upload_png`, and
`chart_data.gate_allows`.

## Data shaping

New module `app/services/approvals_analysis.py` (pure functions, no network).

Row rules match `build_report_matrix` / `build_rep_leaderboard`: include a row
only when **Date Approved** parses and **Client** is non-blank. Sum the amount
column (`APPROVALS_COLS`). Timezone for “today” is `REPORT_TZ`
(default `America/New_York`).

### Weekly

- Last **6 completed** Monday–Sunday weeks. The in-progress week is omitted.
- Label is the Sunday, zero-padded: `WE 08.08`.
- A completed week with no deals still gets a `$0.00` bar (always 6 bars).

### Monthly

- Last **5 completed** calendar months, then the **current** month only if its
  total is greater than 0.
- Labels: `Apr 2026` (English 3-letter month + year).
- A completed month with no deals still gets a `$0.00` bar.

Public function:

```
build_approvals_analysis_series(values, kind, *, today, cols) -> list[tuple[str, float]]
```

`kind` is `"weekly"` or `"monthly"`. Always emit the full bar count (zeros
included) so the axis is stable. If **every** bar in a series is `$0`, skip
that chart. If every requested kind is all-zero, post nothing (exit 0).

Configurable defaults (env, matching sales-analysis knobs):
`APPROVALS_ANALYSIS_WEEKLY_WEEKS=6`, `APPROVALS_ANALYSIS_MONTHLY_MONTHS=5`.

## Rendering and CLI

`scripts/approvals_analysis.py` mirrors `scripts/sales_analysis.py`:

- `--kind weekly|monthly|both`
- `--gate none|first-monday|last-day` (scheduled guard; cron-job.org usually
  sends `none` because the calendar is in the cron job)
- `--output file|slack`
- `--out-path` (file mode writes `*-weekly.png` / `*-monthly.png`)

Fetch uses existing approvals sheet settings (`APPROVALS_SPREADSHEET_ID`,
`APPROVALS_GID`, `APPROVALS_SHEET_NAME`, `APPROVALS_RANGE`).

Channel / token:

- Channel: `--channel` or `CHANNEL` env, else `APPROVALS_CHANNEL_ID`, else
  `SLACK_CHANNEL_ID`.
- Token: `APPROVALS_SLACK_BOT_TOKEN` else `SLACK_BOT_TOKEN`.

On-demand workflow sets `CHANNEL` to the Slack `channel_id` from the slash
command so the chart lands in the invoking channel. Scheduled workflow leaves
`CHANNEL` unset so the dedicated approvals channel is used.

Slack comment: `:bar_chart: *WEEKLY APPROVALS ANALYSIS*` (or monthly / both).

## Slack command

In `app/services/slack_commands.py` add `/approvalsanalysis`:

| Arg | Workflow | Inputs |
|---|---|---|
| (blank) or `weekly` | `approvals-analysis-ondemand.yml` | `report=weekly`, `channel=<id>` |
| `monthly` | same | `report=monthly`, `channel=<id>` |

Invalid arg → usage:
`Usage: `/approvalsanalysis [weekly|monthly]` (default: weekly)``.

Ack text: `:bar_chart: Generating the *weekly approvals analysis* report — …`
(same pattern as `/salesanalysis`).

The command lives in the **existing approvals Slack app**
(`SLACK_SIGNING_SECRET_APPROVAL`). One-time Slack UI step after merge: Slash
Commands → Create `/approvalsanalysis` → Request URL
`https://lgf-automation.vercel.app/api/slack`. No new Vercel env.

## GitHub workflows

No `schedule:` in the YAML. Scheduling is owned by cron-job.org, same as
snapshot / sales analysis / approvals tables.

### `approvals-analysis-ondemand.yml`

`workflow_dispatch` inputs: `report` (`weekly`|`monthly`, default weekly),
`channel` (Slack channel ID). Job installs uv, Playwright, writes the service
account from `GOOGLE_SERVICE_ACCOUNT_JSON`, then:

```
uv run python scripts/approvals_analysis.py --kind "$KIND" --output slack
```

Env: `SLACK_BOT_TOKEN`, `APPROVALS_SLACK_BOT_TOKEN`, `APPROVALS_CHANNEL_ID`,
`CHANNEL` from `inputs.channel`, `KIND` from `inputs.report`.

### `approvals-analysis-scheduled.yml`

`workflow_dispatch` inputs: `kind` (`weekly`|`monthly`|`both`, default both),
`gate` (`none`|`first-monday`|`last-day`, default none). Same install steps.
Cadence is in cron-job.org, so production jobs send `gate=none`.

## cron-job.org

Use the existing GitHub PAT already used for snapshot / approvals / sales
analysis (Actions: Read and write on `arthur-lgf/lgf-automation`). Full PAT and
account setup remains in `docs/SCHEDULING.md`. Clone an existing job; change
only title, URL, schedule, and body.

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

Workflows must be on `main` before the jobs will 204. A 204 from cron-job.org
plus a GitHub Actions run “Triggered via API” is success. Slack should show the
PNG in `APPROVALS_CHANNEL_ID`. Document this clone-and-edit flow in
`docs/SETUP-approvals-analysis.md` and point at `docs/SCHEDULING.md` for PAT /
header details.

## Tests

`tests/test_approvals_analysis.py`:

- Weekly: given `today`, last 6 completed Mon–Sun weeks, Sunday `WE MM.DD` labels,
  current week excluded, empty weeks are `$0`.
- Monthly: 5 completed months + current only when amount > 0; `$0` completed
  months still appear; label `Apr 2026`.
- Same Client-blank skip as the table reports (totals match a
  `build_report_matrix` sum over each window).

`tests/test_slack_commands.py`:

- `/approvalsanalysis` default weekly; `monthly` accepted; bad arg usage;
  dispatch workflow name `approvals-analysis-ondemand.yml`.

No Playwright tests for the PNG; renderer coverage already lives in
`tests/test_chart_renderer.py`.

## Docs to update

- New `docs/SETUP-approvals-analysis.md` (slash command + the two cron-job.org
  jobs, modeled on `docs/SETUP-sales-analysis.md`).
- `docs/SETUP-slack-commands.md`: add `/approvalsanalysis` to the command list
  and the Slack-app table.
- `README.md`: one short paragraph pointing at the setup doc.

## Error handling

| Case | Behavior |
|---|---|
| Sheet access failure | CLI exit 2; workflow fails (cron-job.org will retry / notify) |
| Bad `REPORT_TZ` | CLI exit 2 |
| Screenshot failure | CLI exit 3 |
| Slack upload failure | CLI exit 4 |
| Empty / all-zero series | Skip that kind; if all requested kinds are all-zero, exit 0 and post nothing |
| Invalid slash arg | Ephemeral usage message; no workflow dispatch |

## Implementation notes

- Keep `approvals.py` table/leaderboard logic untouched.
- Reuse `_cell`, `parse_date`, `parse_amount` from `app.services.approvals`.
- `chart_renderer` is shared; do not fork styles unless a title-length issue
  appears (the word APPROVALS is longer than SALES).
- After merge: create the Slack slash command, push `main`, then create the two
  [cron-job.org](https://cron-job.org/) jobs. Local dry run:
  `uv run python scripts/approvals_analysis.py --kind both --output file`.
