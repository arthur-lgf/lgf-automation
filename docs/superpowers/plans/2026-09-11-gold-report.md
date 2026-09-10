# Monthly Gold Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `/gold [monthly]` so Slack posts the V:Y Gold Report table PNG from the Sales Report tab.

**Architecture:** Clone `sales-ondemand.yml`. Dedicated `scripts/gold.py` (monthly V:Y only; dual Slack channels). Wire `/gold` in `slack_commands.py` like `/skools`.

**Tech Stack:** Python 3.11, pytest, GitHub Actions `workflow_dispatch`, Vercel `/api/slack`, `scripts/gold.py`.

## Global Constraints

- Spreadsheet `12glaANnP2BsQfH_kHfRlzA40JdWAU-PJgDT-56yRV8k`, gid `170384010`, range `V1:Y50`.
- Theme `gold`, `ONLY_RANKED=1`, title `Monthly Gold Report`.
- On demand only; `/gold` and `/gold monthly` valid; `/gold daily` usage error.
- Do not modify `scripts/snapshot.py` or `snapshot.yml`.
- `/gold` uses dedicated Slack app `A0C11GQ6ESE` (`SLACK_SIGNING_SECRET_GOLD`, `GOLD_SLACK_BOT_TOKEN`).

---

## File map

| File | Role |
|---|---|
| `tests/test_slack_commands.py` | `/gold` parse + dispatch tests |
| `app/services/slack_commands.py` | `/gold` → `gold-ondemand.yml` |
| `.github/workflows/gold-ondemand.yml` | Clone of sales-ondemand; calls `scripts/gold.py` |
| `scripts/gold.py` | Monthly Gold only (V1:Y50); posts to C0ATW4FSK0X + C0BFN82DDLN |
| `docs/SETUP-slack-commands.md` | Command list + Slack app create-command row |

---

### Task 1: Slash command

- [ ] **Step 1: Write failing tests** in `tests/test_slack_commands.py`:
  - `/gold` and `/gold monthly` → workflow `gold-ondemand.yml`, inputs `report=monthly` + channel, label contains `gold`
  - `/gold daily` and `/gold weekly` raise `CommandError` whose message includes ``[monthly]``
  - unknown-command message lists `/gold`
  - `handle_slash_request` for `/gold monthly` dispatches that workflow
- [ ] **Step 2: Run** `uv run pytest tests/test_slack_commands.py -q` — expect fail
- [ ] **Step 3: Implement** in `app/services/slack_commands.py`: `_GOLD_REPORTS = ("monthly",)`, usage, parse branch, unknown-command list
- [ ] **Step 4: Re-run tests** — pass
- [ ] **Step 5: Commit** with message: `Add /gold monthly slash command dispatching the Gold Report workflow.`

### Task 2: Workflow + docs

- [ ] **Step 1: Copy** `.github/workflows/sales-ondemand.yml` to `gold-ondemand.yml`. Change name, job, comments, `report` options to `monthly` only, range `V1:Y50`, title `Monthly Gold Report`. Keep spreadsheet id, gid, `ONLY_RANKED`, sales bot token. Do not set a custom theme (default `dark_green`).
- [ ] **Step 2: Update** `docs/SETUP-slack-commands.md`: add `/gold [monthly]` to the command list, slash-command table, and note it lives in the Sales app.
- [ ] **Step 3: YAML sanity** — parse `gold-ondemand.yml` as YAML
- [ ] **Step 4: Run** `uv run pytest tests/test_slack_commands.py -q`
- [ ] **Step 5: Commit** with message: `Add gold-ondemand workflow for the Monthly Gold Report table.`
