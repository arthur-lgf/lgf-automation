# Approvals Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add weekly/monthly approvals bar charts that look and ship like Sales Analysis (`/salesanalysis` + cron-job.org), without changing the existing `/approvals` tables.

**Architecture:** Clone the Sales Analysis pipeline. Aggregate APPTRACK `APPS` rows (Date Approved + amount) into a `[(label, amount), …]` series, then reuse `render_bar_chart` → Playwright → Slack. On-demand slash command dispatches `approvals-analysis-ondemand.yml`; [cron-job.org](https://cron-job.org/) dispatches `approvals-analysis-scheduled.yml`.

**Tech Stack:** Python 3.11, pytest, existing `app.services.approvals` parsers, `chart_renderer.render_bar_chart`, `chart_data.gate_allows`, GitHub Actions `workflow_dispatch`, Vercel `/api/slack`, Slack slash commands.

## Global Constraints

- Do not modify `app/services/approvals.py` table/leaderboard behavior, `/approvals`, or APPTRACK sheet layout.
- Clone Sales Analysis file-for-file: CLI flags `--kind` / `--gate` / `--output`, workflow input names `report` (ondemand) and `kind`+`gate` (scheduled), Slack command `/approvalsanalysis [weekly|monthly]`.
- Chart titles: `WEEKLY APPROVALS ANALYSIS` / `MONTHLY APPROVALS ANALYSIS`. Reuse `app/services/chart_renderer.py` with no style fork unless a title clips.
- Weekly: last 6 completed Monday–Sunday weeks, labels `WE 08.08` (Sunday, zero-padded), `$0.00` bars for empty weeks, current week omitted.
- Monthly: last 5 completed calendar months + current month only if amount > 0, labels `Apr 2026`, `$0.00` bars for empty completed months.
- Same row filter as the tables: parseable Date Approved AND non-blank Client.
- If every bar in a series is `$0`, skip that chart; if all requested kinds are all-zero, exit 0 and post nothing.
- No new secrets. Workflows map `APPROVALS_SLACK_BOT_TOKEN` / `APPROVALS_CHANNEL_ID` onto `SLACK_BOT_TOKEN` / `SLACK_CHANNEL_ID` the same way sales-analysis maps its secrets.
- Scheduling lives in cron-job.org, not GitHub `schedule:`.
- TDD: failing tests before implementation. Run tests with `uv run pytest`.

## File map (Sales Analysis → Approvals Analysis)

| Sales Analysis | Approvals Analysis |
|---|---|
| `app/services/chart_data.py` (`build_analysis_series`) | Create `app/services/approvals_analysis.py` (`build_approvals_analysis_series`) |
| `scripts/sales_analysis.py` | Create `scripts/approvals_analysis.py` (same flags, titles, gate, upload) |
| `.github/workflows/sales-analysis-ondemand.yml` | Create `.github/workflows/approvals-analysis-ondemand.yml` |
| `.github/workflows/sales-analysis-scheduled.yml` | Create `.github/workflows/approvals-analysis-scheduled.yml` |
| `/salesanalysis` in `slack_commands.py` | `/approvalsanalysis` next to it |
| `docs/SETUP-sales-analysis.md` | Create `docs/SETUP-approvals-analysis.md` |
| `tests/test_chart_data.py` | Create `tests/test_approvals_analysis.py` |

Do not generalize `scripts/sales_analysis.py` to take a source flag.

---

### Task 1: Series builder (TDD)

**Files:**
- Create: `tests/test_approvals_analysis.py`
- Create: `app/services/approvals_analysis.py`
- Modify: `app/config.py` (add weekly/monthly limit fields next to the sales-analysis knobs)
- Modify: `.env.example` (document the two new knobs)

**Interfaces:**
- Consumes: `app.services.approvals._cell`, `parse_date`, `parse_amount`, `DEFAULT_COLS`
- Produces: `build_approvals_analysis_series(values: list[list[str]], kind: str, *, today: date, cols: dict[str, int] | None = None, weekly_weeks: int = 6, monthly_months: int = 5) -> list[tuple[str, float]]`
- Produces Settings fields: `approvals_analysis_weekly_weeks: int` (default 6, alias `APPROVALS_ANALYSIS_WEEKLY_WEEKS`), `approvals_analysis_monthly_months: int` (default 5, alias `APPROVALS_ANALYSIS_MONTHLY_MONTHS`)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_approvals_analysis.py`:

```python
"""Bucket APPS rows into weekly/monthly approvals-analysis bar series."""
from datetime import date

import pytest

from app.services import approvals as approvals_service
from app.services import approvals_analysis as aa

# Friday. Last completed Sunday is 9/6/2026. Six weeks: WE 08.02 … WE 09.06.
TODAY = date(2026, 9, 11)
COLS = approvals_service.DEFAULT_COLS


def _row(*, approved: str, amount: str, client: str = "Co") -> list[str]:
    row = [""] * 12
    row[COLS["date_approved"]] = approved
    row[COLS["client"]] = client
    row[COLS["amount"]] = amount
    return row


def test_weekly_six_completed_weeks_sunday_labels():
    values = [
        _row(approved="8/2/2026", amount="$1,000.00"),   # Sun 8/2
        _row(approved="8/5/2026", amount="$2,000.00"),   # week ending 8/9
        _row(approved="9/3/2026", amount="$3,000.00"),   # week ending 9/6
        _row(approved="9/7/2026", amount="$9,999.00"),   # in-progress week — excluded
    ]
    series = aa.build_approvals_analysis_series(
        values, "weekly", today=TODAY, cols=COLS, weekly_weeks=6
    )
    labels = [label for label, _ in series]
    assert labels == [
        "WE 08.02", "WE 08.09", "WE 08.16", "WE 08.23", "WE 08.30", "WE 09.06",
    ]
    by = dict(series)
    assert by["WE 08.02"] == 1000.0
    assert by["WE 08.09"] == 2000.0
    assert by["WE 08.16"] == 0.0
    assert by["WE 09.06"] == 3000.0
    assert "WE 09.13" not in labels


def test_weekly_skips_blank_client_like_tables():
    values = [
        _row(approved="9/3/2026", amount="$1,000.00", client=""),
        _row(approved="9/3/2026", amount="$400.00", client="Acme"),
    ]
    series = aa.build_approvals_analysis_series(
        values, "weekly", today=TODAY, cols=COLS, weekly_weeks=6
    )
    assert dict(series)["WE 09.06"] == 400.0


def test_monthly_five_completed_plus_current_with_data():
    values = [
        _row(approved="4/10/2026", amount="$10.00"),
        _row(approved="5/10/2026", amount="$20.00"),
        _row(approved="6/10/2026", amount="$30.00"),
        _row(approved="7/10/2026", amount="$40.00"),
        _row(approved="8/10/2026", amount="$50.00"),
        _row(approved="9/5/2026", amount="$60.00"),
        _row(approved="3/10/2026", amount="$999.00"),  # older than 5 completed
    ]
    series = aa.build_approvals_analysis_series(
        values, "monthly", today=TODAY, cols=COLS, monthly_months=5
    )
    assert [label for label, _ in series] == [
        "Apr 2026", "May 2026", "Jun 2026", "Jul 2026", "Aug 2026", "Sep 2026",
    ]
    assert series[-1] == ("Sep 2026", 60.0)


def test_monthly_drops_current_month_when_zero():
    values = [
        _row(approved="4/10/2026", amount="$10.00"),
        _row(approved="5/10/2026", amount="$20.00"),
        _row(approved="6/10/2026", amount="$30.00"),
        _row(approved="7/10/2026", amount="$40.00"),
        _row(approved="8/10/2026", amount="$50.00"),
    ]
    series = aa.build_approvals_analysis_series(
        values, "monthly", today=TODAY, cols=COLS, monthly_months=5
    )
    assert [label for label, _ in series] == [
        "Apr 2026", "May 2026", "Jun 2026", "Jul 2026", "Aug 2026",
    ]


def test_all_zero_series_returns_empty():
    assert aa.build_approvals_analysis_series(
        [], "weekly", today=TODAY, cols=COLS, weekly_weeks=6
    ) == []
    assert aa.build_approvals_analysis_series(
        [_row(approved="1/1/2020", amount="$1.00")],
        "weekly", today=TODAY, cols=COLS, weekly_weeks=6,
    ) == []


def test_invalid_kind_raises():
    with pytest.raises(ValueError):
        aa.build_approvals_analysis_series([], "quarterly", today=TODAY, cols=COLS)


def test_weekly_totals_match_report_matrix_for_one_week():
    values = [
        _row(approved="9/1/2026", amount="$100.00"),
        _row(approved="9/6/2026", amount="$50.50"),
        _row(approved="9/1/2026", amount="$10.00", client=""),
    ]
    series = aa.build_approvals_analysis_series(
        values, "weekly", today=TODAY, cols=COLS, weekly_weeks=6
    )
    report = approvals_service.build_report_matrix(
        values, date(2026, 8, 31), date(2026, 9, 6), cols=COLS
    )
    assert dict(series)["WE 09.06"] == report.total
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_approvals_analysis.py -v`

Expected: FAIL with `ModuleNotFoundError` or `ImportError` for `app.services.approvals_analysis`.

- [ ] **Step 3: Add Settings knobs**

In `app/config.py`, immediately after `approvals_cols_map` and before the Sales Analysis block, insert:

```python
    # --- Approvals Analysis charts (scripts/approvals_analysis.py) ----------
    # Weekly + monthly bar charts aggregated from the APPS tab (same sheet as
    # the tables). Mirrors SALES_ANALYSIS_WEEKLY_WEEKS / _MONTHLY_MONTHS.
    approvals_analysis_weekly_weeks: int = Field(
        default=6, alias="APPROVALS_ANALYSIS_WEEKLY_WEEKS"
    )
    approvals_analysis_monthly_months: int = Field(
        default=5, alias="APPROVALS_ANALYSIS_MONTHLY_MONTHS"
    )
```

Append to `.env.example`:

```
# Approvals analysis bar charts (scripts/approvals_analysis.py)
APPROVALS_ANALYSIS_WEEKLY_WEEKS=6
APPROVALS_ANALYSIS_MONTHLY_MONTHS=5
```

- [ ] **Step 4: Implement the series builder**

Create `app/services/approvals_analysis.py`:

```python
"""Bucket APPS rows into a weekly/monthly bar-chart series.

Pure data shaping — no network, no rendering. The series is fed to
``chart_renderer.render_bar_chart`` the same way Sales Analysis uses
``chart_data.build_analysis_series``.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from app.services.approvals import DEFAULT_COLS, _cell, parse_amount, parse_date

_MONTH_ABBR = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)


def _sunday_of(day: date) -> date:
    return day + timedelta(days=(6 - day.weekday()))


def _last_completed_sunday(today: date) -> date:
    return today - timedelta(days=today.weekday() + 1)


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    idx = year * 12 + (month - 1) + delta
    return idx // 12, idx % 12 + 1


def _iter_deals(values: list[list[str]], cols: dict[str, int]):
    for row in values:
        approved = parse_date(_cell(row, cols["date_approved"]))
        if approved is None:
            continue
        if not _cell(row, cols["client"]):
            continue
        yield approved, parse_amount(_cell(row, cols["amount"]))


def _all_zero(series: list[tuple[str, float]]) -> bool:
    return not series or all(amount == 0.0 for _, amount in series)


def build_approvals_analysis_series(
    values: list[list[str]],
    kind: str,
    *,
    today: date,
    cols: Optional[dict[str, int]] = None,
    weekly_weeks: int = 6,
    monthly_months: int = 5,
) -> list[tuple[str, float]]:
    """Return ``[(label, amount), …]`` oldest-first.

    ``kind`` is ``"weekly"`` or ``"monthly"``. All-zero series returns ``[]``
    so the CLI skips posting.
    """
    if kind not in ("weekly", "monthly"):
        raise ValueError(f"kind must be 'weekly' or 'monthly'; got {kind!r}")
    cols = cols or DEFAULT_COLS
    if kind == "weekly":
        series = _weekly_series(values, today, cols, weekly_weeks)
    else:
        series = _monthly_series(values, today, cols, monthly_months)
    return [] if _all_zero(series) else series


def _weekly_series(
    values: list[list[str]], today: date, cols: dict[str, int], n: int
) -> list[tuple[str, float]]:
    if n <= 0:
        return []
    last_sunday = _last_completed_sunday(today)
    sundays = [last_sunday - timedelta(days=7 * i) for i in range(n - 1, -1, -1)]
    totals = {sunday: 0.0 for sunday in sundays}
    lo, hi = sundays[0] - timedelta(days=6), sundays[-1]
    for approved, amount in _iter_deals(values, cols):
        if approved < lo or approved > hi:
            continue
        sunday = _sunday_of(approved)
        if sunday in totals:
            totals[sunday] += amount
    return [
        (f"WE {sunday.month:02d}.{sunday.day:02d}", totals[sunday])
        for sunday in sundays
    ]


def _monthly_series(
    values: list[list[str]], today: date, cols: dict[str, int], n: int
) -> list[tuple[str, float]]:
    if n <= 0:
        return []
    last_prev = today.replace(day=1) - timedelta(days=1)
    completed: list[tuple[int, int]] = []
    for i in range(n - 1, -1, -1):
        completed.append(_shift_month(last_prev.year, last_prev.month, -i))
    buckets = {key: 0.0 for key in completed}
    current_key = (today.year, today.month)
    current_total = 0.0
    for approved, amount in _iter_deals(values, cols):
        key = (approved.year, approved.month)
        if key in buckets:
            buckets[key] += amount
        elif key == current_key:
            current_total += amount
    series = [
        (f"{_MONTH_ABBR[month - 1]} {year}", buckets[(year, month)])
        for year, month in completed
    ]
    if current_total > 0:
        y, m = current_key
        series.append((f"{_MONTH_ABBR[m - 1]} {y}", current_total))
    return series
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_approvals_analysis.py -v`

Expected: PASS (7 tests).

- [ ] **Step 6: Commit**

```bash
git add tests/test_approvals_analysis.py app/services/approvals_analysis.py app/config.py .env.example
git commit -m "$(cat <<'EOF'
Add approvals-analysis series builder matching sales-analysis windows.

EOF
)"
```

---

### Task 2: Slash command (TDD)

**Files:**
- Modify: `tests/test_slack_commands.py`
- Modify: `app/services/slack_commands.py`

**Interfaces:**
- Consumes: existing `parse_command` / `handle_slash_request`
- Produces: `/approvalsanalysis` → workflow `approvals-analysis-ondemand.yml`, inputs `{"report": "weekly"|"monthly", "channel": channel_id}`, labels `weekly approvals analysis` / `monthly approvals analysis`

- [ ] **Step 1: Write the failing tests**

In `tests/test_slack_commands.py`, next to `test_parse_salesanalysis_default_and_periods`, add:

```python
def test_parse_approvalsanalysis_default_and_periods():
    r = sc.parse_command("/approvalsanalysis", "", "C7")
    assert r.workflow == "approvals-analysis-ondemand.yml"
    assert r.inputs == {"report": "weekly", "channel": "C7"}
    assert "analysis" in r.report_label.lower()
    assert sc.parse_command("/approvalsanalysis", "monthly", "C7").inputs["report"] == "monthly"
```

In `test_parse_bad_args_raise_usage`, add:

```python
    with pytest.raises(sc.CommandError) as e4:
        sc.parse_command("/approvalsanalysis", "daily", "C1")
    assert "weekly" in str(e4.value)
```

Next to `test_handle_dispatches_salesanalysis`, add:

```python
def test_handle_dispatches_approvalsanalysis():
    body = _form(command="/approvalsanalysis", text="monthly", channel_id="C55")
    ts = "1700000000"
    calls = []
    resp = sc.handle_slash_request(
        raw_body=body,
        headers={"X-Slack-Signature": _sign(ts, body), "X-Slack-Request-Timestamp": ts},
        signing_secret=SECRET, github_token="ghp", repo="o/r", now=1700000003,
        dispatcher=lambda **k: calls.append(k) or 204,
    )
    assert resp.status == 200
    assert len(calls) == 1
    assert calls[0]["workflow"] == "approvals-analysis-ondemand.yml"
    assert calls[0]["inputs"] == {"report": "monthly", "channel": "C55"}
    assert "monthly approvals analysis" in resp.body["text"].lower()
```

In `parse_command`'s unknown-command error test, the message currently lists `/approvals`, `/sales`, `/salesanalysis`, `/skools`. After this task it must also mention `/approvalsanalysis`. Update that assertion if it becomes too strict; the usage string should list `/approvalsanalysis`.

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `uv run pytest tests/test_slack_commands.py::test_parse_approvalsanalysis_default_and_periods tests/test_slack_commands.py::test_handle_dispatches_approvalsanalysis -v`

Expected: FAIL (`CommandError` unknown command).

- [ ] **Step 3: Wire the command like `/salesanalysis`**

In `app/services/slack_commands.py`:

1. After `_SALES_ANALYSIS_REPORTS = ("weekly", "monthly")` add nothing new (reuse that tuple) **or** add `_APPROVALS_ANALYSIS_REPORTS = ("weekly", "monthly")` and use it — prefer the dedicated name so copy stays obvious.
2. After `_SALES_ANALYSIS_LABELS` add:

```python
_APPROVALS_ANALYSIS_REPORTS = ("weekly", "monthly")
_APPROVALS_ANALYSIS_LABELS = {
    "weekly": "weekly approvals analysis",
    "monthly": "monthly approvals analysis",
}
```

3. After `_usage_salesanalysis` add:

```python
def _usage_approvalsanalysis() -> str:
    return "Usage: `/approvalsanalysis [weekly|monthly]` (default: weekly)"
```

4. In `parse_command`, immediately after the `salesanalysis` branch, add a clone:

```python
    if cmd == "approvalsanalysis":
        report = arg or "weekly"
        if report not in _APPROVALS_ANALYSIS_REPORTS:
            raise CommandError(_usage_approvalsanalysis())
        return CommandResult(
            "approvals-analysis-ondemand.yml",
            {"report": report, "channel": channel_id},
            _APPROVALS_ANALYSIS_LABELS[report],
        )
```

5. Update the unknown-command message to include `/approvalsanalysis`.

- [ ] **Step 4: Run slack-command tests**

Run: `uv run pytest tests/test_slack_commands.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_slack_commands.py app/services/slack_commands.py
git commit -m "$(cat <<'EOF'
Add /approvalsanalysis slash command dispatching the analysis workflow.

EOF
)"
```

---

### Task 3: CLI cloned from `scripts/sales_analysis.py`

**Files:**
- Create: `scripts/approvals_analysis.py`
- Modify: `.vercelignore` (exclude the new service module from the Vercel listener, same as `app/services/approvals.py`)

**Interfaces:**
- Consumes: `build_approvals_analysis_series`, `render_bar_chart`, `gate_allows`, `fetch_values`, `snapshot_html`, `upload_png` / `upload_pngs`, Settings approvals sheet + analysis week/month knobs
- Produces: CLI `scripts/approvals_analysis.py --kind weekly|monthly|both --gate none|first-monday|last-day --output file|slack`

This script is a structural copy of `scripts/sales_analysis.py`. Differences vs sales (only these):

- Fetch APPTRACK APPS via `settings.approvals_spreadsheet_id` / `approvals_gid` / `approvals_sheet_name` / `approvals_range` (no hardcoded Analysis-tab gid, no Sales Report current-month override).
- Series from `build_approvals_analysis_series(..., cols=settings.approvals_cols_map(), weekly_weeks=settings.approvals_analysis_weekly_weeks, monthly_months=settings.approvals_analysis_monthly_months)`.
- Titles `_TITLES = {"weekly": "Weekly Approvals Analysis", "monthly": "Monthly Approvals Analysis"}`.
- Channel/token: `settings.slack_channel_id` / `settings.slack_bot_token` (workflows inject the approvals secrets onto those env vars, identical to how sales-analysis uses `SLACK_*`).
- Filenames `approvals-analysis-weekly.png` / `approvals-analysis-monthly.png`.
- Slack comments `:bar_chart: *Weekly Approvals Analysis*` / monthly / `*Approvals Analysis* — weekly & monthly`.
- Default `--out-path` `approvals_analysis.png`.
- All-zero series already returns `[]` from the builder; keep the sales “skip that chart / no images → exit 0” behavior. Do **not** post a “No … data yet.” Slack text unless sales still does — sales does post that text when `images` is empty. Match sales: call `post_message` with `"No approvals analysis data yet."`.

- [ ] **Step 1: Create `scripts/approvals_analysis.py`**

Copy `scripts/sales_analysis.py` to `scripts/approvals_analysis.py` and apply the differences above. Keep argparse flags, `gate_allows`, screenshot `selector="#chart"`, and the single-vs-multi `upload_png` / `upload_pngs` branches byte-equivalent.

Fetch block:

```python
    try:
        cols = settings.approvals_cols_map()
    except ValueError as exc:
        print(f"::error::config: {exc}", file=sys.stderr)
        return 2

    spreadsheet_id = args.spreadsheet_id or settings.approvals_spreadsheet_id
    gid = args.gid if args.gid is not None else settings.approvals_gid
    range_a1 = args.range_a1 or settings.approvals_range

    try:
        values = fetch_values(
            spreadsheet_id=spreadsheet_id,
            range_a1=range_a1,
            sheet_name=settings.approvals_sheet_name,
            gid=gid,
            source="api",
            credentials_path=settings.google_application_credentials,
        )
    except SheetAccessError as exc:
        print(f"::error::sheet_access: {exc}", file=sys.stderr)
        return 2
```

Series block (replaces `build_analysis_series` + sales-report override):

```python
        n = (
            settings.approvals_analysis_weekly_weeks
            if kind == "weekly"
            else settings.approvals_analysis_monthly_months
        )
        series = build_approvals_analysis_series(
            values,
            kind,
            today=today,
            cols=cols,
            weekly_weeks=n if kind == "weekly" else settings.approvals_analysis_weekly_weeks,
            monthly_months=n if kind == "monthly" else settings.approvals_analysis_monthly_months,
        )
```

Cleaner: pass both knobs every time:

```python
        series = build_approvals_analysis_series(
            values,
            kind,
            today=today,
            cols=cols,
            weekly_weeks=settings.approvals_analysis_weekly_weeks,
            monthly_months=settings.approvals_analysis_monthly_months,
        )
```

Channel/token (sales-analysis shape):

```python
    channel = settings.slack_channel_id
    token = settings.slack_bot_token
```

Keep `--spreadsheet-id`, `--gid`, `--range`, `--kind`, `--gate`, `--output`, `--out-path` argparse flags identical to sales (including `KIND` / `GATE` / `OUTPUT` / `OUT_PATH` env fallbacks).

- [ ] **Step 2: Exclude the new module from Vercel**

In `.vercelignore`, add `app/services/approvals_analysis.py` next to `app/services/approvals.py`.

- [ ] **Step 3: Syntax-check the CLI**

Run: `uv run python -m py_compile scripts/approvals_analysis.py`

Expected: exit 0.

- [ ] **Step 4: Local dry-run (optional if credentials exist)**

Run: `uv run python scripts/approvals_analysis.py --kind both --output file --out-path /tmp/approvals_analysis.png`

Expected: writes `/tmp/approvals_analysis-weekly.png` and `/tmp/approvals_analysis-monthly.png` (or skips a kind if all-zero). Open the PNGs and confirm they match Sales Analysis chrome (black card, gold title, colored bars).

- [ ] **Step 5: Commit**

```bash
git add scripts/approvals_analysis.py .vercelignore
git commit -m "$(cat <<'EOF'
Add approvals-analysis CLI cloned from sales-analysis.

EOF
)"
```

---

### Task 4: GitHub workflows cloned from sales-analysis

**Files:**
- Create: `.github/workflows/approvals-analysis-ondemand.yml`
- Create: `.github/workflows/approvals-analysis-scheduled.yml`

**Interfaces:**
- Consumes: `scripts/approvals_analysis.py`
- Produces: `workflow_dispatch` workflows the slash command and cron-job.org can hit

- [ ] **Step 1: Create the on-demand workflow**

Copy `.github/workflows/sales-analysis-ondemand.yml` to `.github/workflows/approvals-analysis-ondemand.yml`. Change only names, script, and secret mapping:

```yaml
name: Approvals Analysis (on demand)

on:
  workflow_dispatch:
    inputs:
      report:
        description: "Which approvals-analysis chart to post"
        required: false
        type: choice
        default: "weekly"
        options:
          - weekly
          - monthly
      channel:
        description: "Slack channel ID to post to (default: APPROVALS_CHANNEL_ID or SLACK_CHANNEL_ID)"
        required: false
        type: string
  # No schedule: this workflow exists for the Slack `/approvalsanalysis` command,
  # fired via the workflow_dispatch REST endpoint (through the Vercel listener).
  # The scheduled charts live in approvals-analysis-scheduled.yml.

permissions:
  contents: read

jobs:
  approvals-analysis:
    name: Approvals Analysis (on demand)
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v3
        with:
          enable-cache: true
          cache-dependency-glob: "uv.lock"

      - name: Set up Python
        run: uv python install 3.11

      - name: Install dependencies
        run: uv sync --no-dev

      - name: Install Playwright Chromium (with system deps)
        run: uv run playwright install --with-deps chromium

      - name: Write Google service-account credentials
        env:
          GOOGLE_SERVICE_ACCOUNT_JSON: ${{ secrets.GOOGLE_SERVICE_ACCOUNT_JSON }}
        run: |
          printf '%s' "$GOOGLE_SERVICE_ACCOUNT_JSON" > "$RUNNER_TEMP/sa.json"
          echo "GOOGLE_APPLICATION_CREDENTIALS=$RUNNER_TEMP/sa.json" >> "$GITHUB_ENV"

      - name: Run on-demand approvals-analysis chart
        env:
          SLACK_BOT_TOKEN: ${{ secrets.APPROVALS_SLACK_BOT_TOKEN || secrets.SLACK_BOT_TOKEN }}
          # /approvalsanalysis passes the channel it was invoked in.
          SLACK_CHANNEL_ID: ${{ inputs.channel || secrets.APPROVALS_CHANNEL_ID || secrets.SLACK_CHANNEL_ID }}
          KIND: ${{ inputs.report || 'weekly' }}
        run: |
          uv run python scripts/approvals_analysis.py --kind "$KIND" --output slack
```

Do **not** hardcode `SPREADSHEET_ID` / `GID` — the CLI uses APPTRACK defaults from Settings, like `scripts/approvals.py`.

Keep the same uv / Playwright / service-account steps as sales-analysis.

- [ ] **Step 2: Create the scheduled workflow**

Copy `.github/workflows/sales-analysis-scheduled.yml` to `.github/workflows/approvals-analysis-scheduled.yml`:

```yaml
name: Approvals Analysis (scheduled)

on:
  workflow_dispatch:
    inputs:
      kind:
        description: "Which chart(s) to post"
        required: false
        type: choice
        default: "both"
        options:
          - weekly
          - monthly
          - both
      gate:
        description: "Optional cadence guard evaluated in ET (usually none)"
        required: false
        type: choice
        default: "none"
        options:
          - none
          - first-monday
          - last-day
  # No in-workflow schedule. Two cron-job.org jobs hit this workflow's
  # workflow_dispatch REST endpoint (see docs/SETUP-approvals-analysis.md):
  #   - every Monday      -> inputs.kind = weekly
  #   - 1st of each month -> inputs.kind = monthly
  # Both cadences are expressed directly in cron-job.org, so gate stays 'none'.

permissions:
  contents: read

jobs:
  approvals-analysis:
    name: Approvals Analysis (scheduled)
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v3
        with:
          enable-cache: true
          cache-dependency-glob: "uv.lock"

      - name: Set up Python
        run: uv python install 3.11

      - name: Install dependencies
        run: uv sync --no-dev

      - name: Install Playwright Chromium (with system deps)
        run: uv run playwright install --with-deps chromium

      - name: Write Google service-account credentials
        env:
          GOOGLE_SERVICE_ACCOUNT_JSON: ${{ secrets.GOOGLE_SERVICE_ACCOUNT_JSON }}
        run: |
          printf '%s' "$GOOGLE_SERVICE_ACCOUNT_JSON" > "$RUNNER_TEMP/sa.json"
          echo "GOOGLE_APPLICATION_CREDENTIALS=$RUNNER_TEMP/sa.json" >> "$GITHUB_ENV"

      - name: Run scheduled approvals-analysis charts
        env:
          SLACK_BOT_TOKEN: ${{ secrets.APPROVALS_SLACK_BOT_TOKEN || secrets.SLACK_BOT_TOKEN }}
          SLACK_CHANNEL_ID: ${{ secrets.APPROVALS_CHANNEL_ID || secrets.SLACK_CHANNEL_ID }}
          KIND: ${{ inputs.kind || 'both' }}
          GATE: ${{ inputs.gate || 'none' }}
        run: |
          uv run python scripts/approvals_analysis.py --kind "$KIND" --gate "$GATE" --output slack
```

- [ ] **Step 3: YAML sanity**

Run: `python -c "import pathlib,yaml; yaml.safe_load(pathlib.Path('.github/workflows/approvals-analysis-ondemand.yml').read_text()); yaml.safe_load(pathlib.Path('.github/workflows/approvals-analysis-scheduled.yml').read_text()); print('ok')"`

If PyYAML is missing: `uv run python -c "import ast; print('skip yaml lib')"` and visually diff against the sales-analysis workflows instead. Expected: parses, structure matches sales (checkout, uv, playwright, sa.json, script).

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/approvals-analysis-ondemand.yml .github/workflows/approvals-analysis-scheduled.yml
git commit -m "$(cat <<'EOF'
Add approvals-analysis GitHub workflows cloned from sales-analysis.

EOF
)"
```

---

### Task 5: Docs (Slack command + cron-job.org)

**Files:**
- Create: `docs/SETUP-approvals-analysis.md`
- Modify: `docs/SETUP-slack-commands.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: workflow filenames and dispatch URL from Task 4
- Produces: operator instructions matching `docs/SETUP-sales-analysis.md`

- [ ] **Step 1: Write `docs/SETUP-approvals-analysis.md`**

Clone `docs/SETUP-sales-analysis.md`. Content:

```markdown
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
- **No new secrets:** reuses `APPROVALS_SLACK_BOT_TOKEN` / `APPROVALS_CHANNEL_ID`
  (fallback `SLACK_BOT_TOKEN` / `SLACK_CHANNEL_ID`), `GOOGLE_SERVICE_ACCOUNT_JSON`,
  and the existing GitHub PAT / Slack signing secret.
```

- [ ] **Step 2: Update `docs/SETUP-slack-commands.md`**

In the command list at the top, add:

```
/approvalsanalysis [weekly|monthly]                 (default: weekly)
```

In the workflows sentence, add `approvals-analysis-ondemand.yml`.

In the Slash Commands table, add a row:

```
| `/approvalsanalysis` | `https://<your-vercel-app>.vercel.app/api/slack` | `[weekly\|monthly]` |
```

Note that `/approvalsanalysis` goes in the **same Slack app as `/approvals`**.

In Test it / troubleshooting, add that `/approvalsanalysis` takes `weekly|monthly` (not `today`).

- [ ] **Step 3: Update README**

After the Approvals report section (after the local curl examples, before `## Local setup`), add:

```markdown
## Approvals analysis (weekly / monthly bar charts)

Same look and shipping path as Sales Analysis. See
[docs/SETUP-approvals-analysis.md](docs/SETUP-approvals-analysis.md).

```bash
uv run python scripts/approvals_analysis.py --kind both --output file
uv run python scripts/approvals_analysis.py --kind weekly --output slack
```

On demand: `/approvalsanalysis [weekly|monthly]`. Scheduled via
[cron-job.org](https://cron-job.org/) (Monday weekly, 1st-of-month monthly)
hitting `approvals-analysis-scheduled.yml`.
```

- [ ] **Step 4: Full test suite**

Run: `uv run pytest -q`

Expected: PASS (existing suite + new tests).

- [ ] **Step 5: Commit**

```bash
git add docs/SETUP-approvals-analysis.md docs/SETUP-slack-commands.md README.md
git commit -m "$(cat <<'EOF'
Document /approvalsanalysis and cron-job.org scheduled posts.

EOF
)"
```

---

## Spec coverage

| Spec requirement | Task |
|---|---|
| `/approvalsanalysis` on demand, tables unchanged | 2, 4 |
| cron-job.org Monday + 1st, docs + dispatch URL | 4, 5 |
| Visual match via `render_bar_chart` | 3 |
| APPS aggregation, Client-blank skip | 1 |
| 6 completed weeks, `WE 08.08` | 1 |
| 5 months + current if > 0, `Apr 2026` | 1 |
| `$0` empty periods; all-zero skips post | 1, 3 |
| CLI `--kind` / `--gate` / file|slack | 3 |
| Workflows cloned from sales-analysis | 4 |
| No new secrets | 4 |
| Tests for bucketing + slash command | 1, 2 |
| SETUP doc + slack-commands + README | 5 |

## Placeholder / type check

- `build_approvals_analysis_series` signature is used the same way in Task 1 tests and Task 3 CLI.
- Workflow input `report` (ondemand) matches slash-command `inputs["report"]` and `KIND: ${{ inputs.report }}`.
- Workflow input `kind` (scheduled) matches cron-job.org body `{"inputs":{"kind":"weekly"}}`.
- No TBD / “similar to Task N” without inlined code.
