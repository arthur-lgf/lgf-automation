# Snapshot Scheduling — cron-job.org → GitHub workflow_dispatch

## 1. Overview

This repo's `.github/workflows/snapshot.yml` no longer carries its own `schedule:`. Scheduling is owned by [cron-job.org](https://cron-job.org), which hits GitHub's `workflow_dispatch` REST endpoint twice a day. cron-job.org handles DST natively (pick wall-clock time in `America/New_York` once and forget), gives sub-minute precision, and avoids GitHub's documented 0–60 min free-tier schedule drift. There are two scheduled jobs: **12:30 PM ET** and **5:00 PM ET**, daily, year-round.

---

## 2. Preconditions

Before creating the PAT, confirm these in the repo. Skipping this step is the #1 cause of unexplained 422 / 403 errors during the curl test in Section 4.

| Check | Where | Required value |
|---|---|---|
| `snapshot.yml` is on the default branch | https://github.com/arthur-lgf/lgf-automation/tree/main/.github/workflows | File exists at `.github/workflows/snapshot.yml` |
| Workflow declares `workflow_dispatch:` | Look at lines 1–15 of that file | `on:` block contains `workflow_dispatch:` |
| Actions are enabled at the repo level | https://github.com/arthur-lgf/lgf-automation/settings/actions | "Allow all actions and reusable workflows" selected |
| The three runtime Secrets are set | https://github.com/arthur-lgf/lgf-automation/settings/secrets/actions | `SLACK_BOT_TOKEN`, `SLACK_CHANNEL_ID`, `GOOGLE_SERVICE_ACCOUNT_JSON` all present |

If `arthur-lgf` is an organization (not a personal account), also confirm Org Settings → Personal access tokens → Settings → **"Allow access via fine-grained personal access tokens"** is enabled. If your org admin hasn't enabled this, skip to the **classic PAT fallback** at the end of Section 3.

---

## 3. Create a fine-grained GitHub PAT

A PAT is the only credential cron-job.org needs from GitHub. We use **fine-grained** (least privilege) so the token can only dispatch this one workflow in this one repo.

1. Go to https://github.com/settings/personal-access-tokens/new (Settings → Developer settings → Personal access tokens → **Fine-grained tokens** → **Generate new token**).
2. **Token name:** `lgf-automation-snapshot-cron`
3. **Resource owner:** select `arthur-lgf` from the dropdown.
   - **If `arthur-lgf` does not appear in this dropdown:** you are not a member of the org, or the org has not enabled fine-grained PATs. Ask an org admin to add you as a member (not just outside collaborator) and to enable fine-grained PATs under Org Settings. Until then, use the classic PAT fallback at the bottom of this section.
4. **Expiration:** 90 days (recommended). Calendar reminder helps — Section 11 covers rotation.
5. **Repository access:** **Only select repositories** → pick `arthur-lgf/lgf-automation`. Do not grant access to other repos.
6. **Permissions → Repository permissions:**
   - **Actions:** Read and write
   - **Metadata:** Read-only is auto-selected when any other permission is granted — leave it. Do not select anything else.
7. Click **Generate token**.
8. **Copy the token immediately.** It starts with `github_pat_` and is shown only once.
9. **If the repo is in an org with SSO enforced:** on the token's detail page, click **Configure SSO** next to the org name → **Authorize**. Without this, every API call returns 403.

**Classic PAT fallback** (if fine-grained isn't available): Settings → Developer settings → **Tokens (classic)** → Generate new token. Scope: `repo` (full control of private repos). For a public repo, `public_repo` is enough. The `workflow` scope alone is **not** sufficient — it permits editing workflow files, not dispatching them.

---

## 4. Verify the PAT works before relying on cron-job.org

This catches PAT scope / branch / SSO problems in 30 seconds — before you set up the cron job and start chasing silent failures.

Substitute your token for `github_pat_YOUR_TOKEN_HERE` in each command.

### 4a. bash (macOS / Linux / Git Bash / WSL)

```bash
export GH_PAT='github_pat_YOUR_TOKEN_HERE'

curl -i -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer $GH_PAT" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  -H "User-Agent: arthur-lgf-snapshot-cron" \
  -H "Content-Type: application/json" \
  https://api.github.com/repos/arthur-lgf/lgf-automation/actions/workflows/snapshot.yml/dispatches \
  -d '{"ref":"main"}'
```

### 4b. PowerShell (Windows)

**Use `curl.exe`** (ships with Windows 10/11) — `Invoke-WebRequest` in PowerShell 5.1 throws a terminating exception on non-2xx and hides the status code you need to debug.

```powershell
$env:GH_PAT = 'github_pat_YOUR_TOKEN_HERE'

curl.exe -i -X POST `
  -H "Accept: application/vnd.github+json" `
  -H "Authorization: Bearer $env:GH_PAT" `
  -H "X-GitHub-Api-Version: 2022-11-28" `
  -H "User-Agent: arthur-lgf-snapshot-cron" `
  -H "Content-Type: application/json" `
  https://api.github.com/repos/arthur-lgf/lgf-automation/actions/workflows/snapshot.yml/dispatches `
  -d '{\"ref\":\"main\"}'
```

If you must use `Invoke-WebRequest`, wrap it so you can see the status code on failure:

```powershell
$env:GH_PAT = 'github_pat_YOUR_TOKEN_HERE'
$headers = @{
  "Accept"               = "application/vnd.github+json"
  "Authorization"        = "Bearer $env:GH_PAT"
  "X-GitHub-Api-Version" = "2022-11-28"
  "User-Agent"           = "arthur-lgf-snapshot-cron"
  "Content-Type"         = "application/json"
}
try {
  $r = Invoke-WebRequest `
    -Uri "https://api.github.com/repos/arthur-lgf/lgf-automation/actions/workflows/snapshot.yml/dispatches" `
    -Method POST -Headers $headers -Body '{"ref":"main"}' -UseBasicParsing
  Write-Host "Status: $($r.StatusCode) (expected 204)"
} catch {
  Write-Host "Status: $($_.Exception.Response.StatusCode.value__)"
  Write-Host "Body:   $($_.ErrorDetails.Message)"
}
```

### 4c. Interpreting the response

| Status | Meaning | Common cause |
|---|---|---|
| **204 No Content** | Success. Workflow dispatch queued. | Everything worked. Open https://github.com/arthur-lgf/lgf-automation/actions to see the new run. |
| **401 Unauthorized** | Bad credentials. | Token has trailing whitespace; token expired; used `token <PAT>` instead of `Bearer <PAT>`; copied placeholder text instead of the real token. |
| **403 Forbidden** | Authenticated but not allowed. Body usually says `Resource not accessible by personal access token`. | Fine-grained PAT missing **Actions: Read and write**; PAT was created without granting access to `arthur-lgf/lgf-automation` specifically; SSO not authorized (click **Configure SSO** on the PAT page → Authorize for `arthur-lgf`); Actions disabled at repo level (Settings → Actions → General); org hasn't enabled fine-grained PATs. |
| **404 Not Found** | Repo or workflow not visible to this token. | Typo in `arthur-lgf` or `lgf-automation`; workflow filename mismatch (path is case-sensitive — `Snapshot.yml` ≠ `snapshot.yml`); `snapshot.yml` not on `main` yet; fine-grained PAT scoped to a different repo (404 instead of 403 to avoid leaking repo existence). |
| **422 Unprocessable Entity** | Authenticated, workflow exists, body rejected. | `"ref":"main"` doesn't match the default branch (check repo home page); `snapshot.yml` doesn't declare `on: workflow_dispatch:`; sent unrecognized `inputs` keys. Read the JSON `message` field for specifics. |

A 204 here means the cron-job.org setup in the next sections will work. Anything else — fix the root cause before continuing.

---

## 5. Create a cron-job.org account

1. Go to https://console.cron-job.org/signup.
2. Free, no credit card. Solve the Cloudflare Turnstile challenge.
   - **If Turnstile keeps failing:** switch to a different network (mobile hotspot, home connection without VPN) or a different browser without ad-blocker / privacy extensions. cron-job.org has no alternative signup path.
3. Confirm the email if you get a verification message in your inbox (the signup flow may or may not send one — confirm if asked, otherwise proceed).
4. Sign in.

Free tier limits you'll touch: **30-second job timeout** (we use < 1 sec — non-issue), **2-day execution log retention** (capture failure details promptly if needed), **64 KB response body capture** (workflow_dispatch returns empty body — non-issue). Unlimited number of jobs. Custom headers and HTTPS are free-tier features.

---

## 6. Create the 12:30 PM ET job

In the cron-job.org dashboard: **Jobs** (left sidebar) → **+ CREATE CRONJOB**.

Fill in exactly:

**General**

| Field | Value |
|---|---|
| Title | `LGF Snapshot - 12:30 PM ET` (use a plain ASCII hyphen-minus, not an em-dash) |
| URL | `https://api.github.com/repos/arthur-lgf/lgf-automation/actions/workflows/snapshot.yml/dispatches` |
| Enabled | On |
| Save responses | On (helpful for debugging the first few runs) |

**Schedule**

| Field | Value |
|---|---|
| Type | Specific times |
| Days of month | Every |
| Months | Every |
| Days of week | Every (Mon, Tue, Wed, Thu, Fri, Sat, Sun) |
| Hours | 12 |
| Minutes | 30 |
| Time zone | `America/New_York` |

(cron-job.org uses the IANA tz database, so picking `America/New_York` handles EDT ↔ EST automatically. Both 12:30 PM and 5:00 PM are well outside the 01:00–03:00 DST transition window, so neither job is at risk of being skipped or duplicated on transition days.)

**Advanced → Request method**

`POST`

**Advanced → Request headers** — use **+ Add header** four times. The `Authorization` value must be `Bearer ` followed by the real `github_pat_...` token you copied in Section 3 step 8. **Do not paste the placeholder text below verbatim.**

| Header | Value |
|---|---|
| `Accept` | `application/vnd.github+json` |
| `Authorization` | `Bearer <PASTE_YOUR_github_pat_HERE>` |
| `X-GitHub-Api-Version` | `2022-11-28` |
| `Content-Type` | `application/json` |

> **Do not set `User-Agent` or `Connection`** — cron-job.org silently overrides those. GitHub's API requires a User-Agent, but cron-job.org's default UA satisfies it.

**Advanced → Request body**

```json
{"ref":"main"}
```

**Notifications**

| Setting | Value |
|---|---|
| Notify on failure | On |
| Notify when job is disabled (auto-disabled after sustained failures) | On |
| Notify on recovery | On |
| Threshold (consecutive failures before notification) | `2` |

**Save**.

---

## 7. Create the 5:00 PM ET job

Use cron-job.org's **Clone** action on the 12:30 job (in the job list, three-dot menu → Clone). On the cloned job change only these:

| Field | Value |
|---|---|
| Title | `LGF Snapshot - 5:00 PM ET` |
| Hours | 17 |
| Minutes | 0 |

Everything else identical. Save.

---

## 8. Verification after the first scheduled fire

**On cron-job.org** (Jobs → click the job → History tab):

- A row with **Status code 204** and an empty Response body = success.
- Anything else: open the row, copy the response body, match it against Section 4c or Section 10. History rows expire after 2 days.

**On GitHub** (https://github.com/arthur-lgf/lgf-automation/actions):

- A new run titled "Snapshot" appears in the list within ~10 seconds of the cron-job.org fire.
- Click the run → top-left summary card shows **Triggered via API** and event type **workflow_dispatch**. (The list view doesn't show the event type; click into the run to see it.)
- Both matrix jobs ("Daily Sales Report" and "Monthly Sales Report") run in parallel and complete green.

**In Slack** (the channel matching `SLACK_CHANNEL_ID` in your Actions secrets):

- Two messages from the bot, one per report, with the rendered PNG attached.
- If GitHub Actions ran green but no Slack message arrived, the `SLACK_CHANNEL_ID` secret likely points to a different channel than you're watching. See Section 10.

---

## 9. Failure notifications (email)

If you set the notification fields in Section 6, you'll get email from cron-job.org when:

- The job fails **2 consecutive times** (`Notify on failure`, threshold 2). One transient blip won't email you.
- cron-job.org auto-disables the job after sustained failures (`Notify when job is disabled`). This typically requires many days of failure. **Critical:** if this fires, the snapshots stop until you re-enable manually.
- The job succeeds again after a streak of failures (`Notify on recovery`).

There is **no webhook-on-failure** option on any tier. Email is the only failure channel. If you need realtime Slack alerts on failure, point a second cron-job at a small healthcheck endpoint you control, and have that endpoint alert Slack.

---

## 10. Troubleshooting

| Symptom | Most likely cause | Fix |
|---|---|---|
| cron-job.org History shows **401** | PAT bad — expired, has trailing whitespace, or revoked. | Rotate the PAT (Section 11) and update the `Authorization` header. |
| cron-job.org History shows **403** | PAT missing `Actions: Read and write`; SSO not authorized; org hasn't enabled fine-grained PATs; Actions disabled at repo level. | Go to your PAT page → re-check Actions permission → click **Configure SSO** → Authorize. Or have org admin enable fine-grained PATs / enable Actions in repo Settings → Actions → General. |
| cron-job.org History shows **404** | Typo in `arthur-lgf/lgf-automation` or `snapshot.yml`; workflow file not on `main`; PAT scoped to the wrong repo. | Verify URL letter-for-letter. Confirm the file exists at https://github.com/arthur-lgf/lgf-automation/blob/main/.github/workflows/snapshot.yml. Recreate the PAT with the correct repo selected. |
| cron-job.org History shows **422** with `Workflow does not have workflow_dispatch trigger` | `snapshot.yml` on `main` lacks `on: workflow_dispatch:`. | Verify the file on `main` contains the workflow_dispatch trigger block. Push the fix to `main`. |
| cron-job.org History shows **422** with `No ref found` | `"ref":"main"` doesn't match the default branch name. | Open the repo home page; if the default branch is `master` or something else, change the body in cron-job.org accordingly. |
| cron-job.org History shows **503** | GitHub Actions API outage. | Check https://www.githubstatus.com. cron-job.org will retry automatically per its schedule; the next fire 4.5 hours later is your next attempt unless you trigger manually. |
| Workflow ran green but **no Slack message** | `SLACK_CHANNEL_ID` GitHub Secret points to a different channel; bot was removed from that channel; bot's token was revoked. | Open the matrix job's "Run … snapshot" step log. The script prints `Uploaded to Slack: https://...permalink` showing the actual destination. If the permalink points at the wrong channel, update the GitHub Secret. |
| **Nothing fires at the scheduled time** | Time zone misconfigured; job disabled; cron-job.org account inactive. | Job detail → confirm timezone reads `America/New_York`. Toggle Enabled off/on to bump the next-fire time. Sign in to cron-job.org at least monthly — abandoned free accounts can be cleaned up per their fair-use policy. |

---

## 11. PAT rotation

Fine-grained PATs have a maximum lifetime (default 90 days for our token). When the token expires, cron-job.org receives 401 on every fire and eventually auto-disables both jobs.

**Cadence:** Rotate every **90 days** at the latest. Calendar reminder for day 80.

**Rotation steps:**

1. GitHub: Settings → Developer settings → Personal access tokens → **Fine-grained tokens** → click **lgf-automation-snapshot-cron** → top-right **Regenerate token** → choose new expiration (90 days) → **Regenerate token** → copy the new `github_pat_...` value. The regenerated token keeps the original repository access and permissions automatically — there is no scope picker on regeneration.
2. If your org enforces SSO: on the regenerated token's page, click **Configure SSO** → **Authorize** for `arthur-lgf`. Without this you'll get 403 on every call.
3. cron-job.org: Jobs → **LGF Snapshot - 12:30 PM ET** → Advanced → Request headers → edit the `Authorization` row → paste `Bearer <new_token>` → Save.
4. Same for **LGF Snapshot - 5:00 PM ET**. (No need to recreate the jobs — only the header changes.)
5. Test by clicking **Run now** in each job's detail page. History should show 204 within 5 seconds.

Old PAT value cannot be recovered — copy it before navigating away.

---

## 12. Fallback / tear-down

### Manual fire (no scheduler needed)

If cron-job.org is down, you can dispatch the workflow yourself:

- **GitHub UI:** Actions → **Snapshot** → **Run workflow** → **Run workflow**. Same effect as the scheduled trigger.
- **curl:** any of the commands in Section 4a/4b.

### Pause one or both scheduled jobs

cron-job.org: Jobs → toggle **Enabled** off. The job is preserved with all configuration; toggle on to resume. No history is lost.

### Delete the scheduling entirely

cron-job.org: Jobs → three-dot menu → Delete. Then revoke the PAT at https://github.com/settings/personal-access-tokens → **lgf-automation-snapshot-cron** → **Revoke**.

### GitHub Actions `schedule:` as a last-resort fallback

If you must restore in-workflow scheduling (e.g., cron-job.org becomes unusable and you haven't picked a replacement yet), add this to `.github/workflows/snapshot.yml`:

```yaml
on:
  workflow_dispatch:
    # ... unchanged ...
  schedule:
    # GitHub cron is UTC and has NO DST awareness. The lines below produce
    # 12:30 PM ET and 5:00 PM ET *only during EST* (early November to mid-March).
    # During EDT (mid-March to early November) they fire one hour later on the
    # wall clock — 1:30 PM ET and 6:00 PM ET respectively. To keep wall-clock
    # parity you must edit these lines at every DST transition (twice a year).
    #
    # EST (winter — currently active): use these
    - cron: "30 17 * * *"   # 12:30 PM ET during EST  (becomes 1:30 PM ET during EDT)
    - cron: "0 22 * * *"    # 5:00 PM ET during EST   (becomes 6:00 PM ET during EDT)
    #
    # EDT (summer): swap to these
    # - cron: "30 16 * * *"  # 12:30 PM ET during EDT (becomes 11:30 AM ET during EST)
    # - cron: "0 21 * * *"   # 5:00 PM ET during EDT  (becomes 4:00 PM ET during EST)
```

Expect 0–60 min drift past the cron time on GitHub's free-tier scheduler. This is strictly worse than cron-job.org for both precision and DST hygiene — use only if cron-job.org isn't an option.
