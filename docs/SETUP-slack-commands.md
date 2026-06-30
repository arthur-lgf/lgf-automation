# On-demand reports from Slack (`/approvals`, `/sales`)

Type a slash command in Slack → a tiny Vercel function verifies it and fires the
matching GitHub workflow → the report posts back in that channel (~1–2 min).

```
/approvals [today|yesterday|last-week|last-month]   (default: today)
/sales [daily|monthly]                              (default: daily)
```

Nothing generates inside the listener — it only **dispatches the existing
workflows** (`approvals.yml`, `sales-ondemand.yml`), so all the report code is
reused. The function (`api/slack.py` + `app/services/slack_commands.py`) is
standard-library only.

---

## One-time setup

### 1. GitHub fine-grained PAT (lets the listener start workflows)
1. GitHub → Settings → Developer settings → **Fine-grained tokens** → Generate new.
2. Repository access: **Only select repositories → `arthur-lgf/lgf-automation`**.
3. Permissions → Repository → **Actions: Read and write**. (Nothing else needed.)
4. Generate, copy the token (starts `github_pat_…`).

### 2. Slack app(s) + slash commands
The `/approvals` and `/sales` commands can live in **one** Slack app or **two
separate apps** — the listener accepts either. Both point at the same Vercel URL.

For each app: https://api.slack.com/apps → **Create New App → From scratch** →
name it → pick your workspace, then:
1. **Slash Commands → Create New Command**:
   | Command | Request URL | Usage hint |
   |---|---|---|
   | `/approvals` | `https://<your-vercel-app>.vercel.app/api/slack` | `[today\|yesterday\|last-week\|last-month]` |
   | `/sales` | `https://<your-vercel-app>.vercel.app/api/slack` | `[daily\|monthly]` |
   (You'll get the real Vercel URL in step 3 — paste a placeholder now and update after deploy.)
2. **Basic Information → App Credentials → Signing Secret** → copy it.
3. **Install App → Install to Workspace.**

**Two apps?** Each has its **own signing secret** — set both in Vercel
(`SLACK_SIGNING_SECRET_APPROVAL` and `SLACK_SIGNING_SECRET_SALES`, step 3). A
request is accepted if it matches **either** secret, so put each command in
whichever app you like. **One app?** Both commands share one secret — set it as
`SLACK_SIGNING_SECRET_APPROVAL` and leave the other blank.

### 3. Deploy the listener to Vercel
1. Vercel → **Add New → Project** → import the `lgf-automation` repo as a **new
   project** (separate from ChatbotAI). Framework preset: **Other**.
2. **Environment Variables** (paste with **no trailing spaces/newlines** — they're
   stripped, but keep them clean):
   | Name | Value |
   |---|---|
   | `SLACK_SIGNING_SECRET_APPROVAL` | signing secret of the app hosting `/approvals` (or your single app) |
   | `SLACK_SIGNING_SECRET_SALES` | signing secret of the app hosting `/sales` (leave blank if one app) |
   | `GITHUB_TOKEN` | the PAT from step 1 |
   | `GITHUB_REPO` | `arthur-lgf/lgf-automation` |
   | `GITHUB_REF_NAME` | `main` (optional; default is `main`) |

   (`SLACK_SIGNING_SECRET` — the legacy single-secret name — still works as a
   fallback if you prefer it.)
3. **Deploy.** Your endpoint is `https://<project>.vercel.app/api/slack`
   (open it in a browser — a GET should say "endpoint is live").
4. Go back to the two slash commands and set their **Request URL** to that
   endpoint; save.

### 4. Let the report bots post in your channels
Reports post **in the channel you ran the command from**, using the existing
report bots. So in each channel where you'll use the commands, invite them:
```
/invite @lgf_approval_report      ← for /approvals
/invite @lgf_sales_report_bot     ← for /sales
```
(If a bot isn't in the channel, the workflow run will fail with `not_in_channel`.)

### 5. Push `main`
The workflows must exist on GitHub for dispatch to find them. After this branch
is merged, `git push origin main`.

---

## Test it
In a channel where `@lgf_approval_report` is a member:
```
/approvals last-week
```
You should see an instant ephemeral "📊 Generating the *weekly approvals*
report…", then the leaderboard image posts in the channel ~1–2 min later (GitHub
Actions spin-up). Watch the run under **GitHub → Actions → Approvals Report**.

## Notes / troubleshooting
- **"Signature verification failed"** → `SLACK_SIGNING_SECRET` in Vercel doesn't
  match the app's signing secret, or the system clock is off (requests older than
  5 min are rejected as replays).
- **Nothing posts but the ack appeared** → check the workflow run in GitHub
  Actions; usually `not_in_channel` (invite the bot) or a bad `GITHUB_TOKEN`.
- **`/approvals` rejected with usage text** → invalid period; valid values are
  `today`, `yesterday`, `last-week`, `last-month`.
- **Change where reports post** → today it posts to the invoking channel; to force
  a fixed channel instead, drop the `channel` input wiring in the workflows (ask
  and I'll adjust).
- The PAT and signing secret live **only** in Vercel env vars — never in the repo.
