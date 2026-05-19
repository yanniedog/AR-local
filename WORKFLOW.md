# Workflow — AR-local

Same ship bar as **Australian Rates** (branch → PR → CI → bot wait → synthesis → thread closure → merge). **Difference:** there is **no Cloudflare** deployment and **no www.australianrates.com** verification for this repo. Steps **8–9** are **local dashboard server** + **`npm run verify:local`** (and Browser MCP when the user asks for UI verification).

Single authoritative source for agents (Cursor, Codex, Claude Code). Self-contained — critical steps are listed here in full.

---

## Ship bar (9 steps + feedback synthesis)

All steps required unless the user **explicitly waives that step in writing for that PR**.

### 1. Branch from fresh main

```sh
git fetch origin && git checkout main && git pull origin main
git checkout -b agent/<slug>   # or feat/ or fix/
```

Distinctive slug (topic + short nonce like `-kj1`). Never reuse another agent's in-flight branch.

### 2. Commit and push

Commit only on the topic branch. `git push -u origin HEAD`.

### 3. PR to main

`gh pr create --base main`. One PR per deliverable. Fix-ups stay on the same branch — do NOT open a second PR.

### 4. CI green

`gh pr checks <n> --watch` until required checks pass (e.g. `ci_result` when present). Fix forward on this PR. After fix pushes, `@mention` reviewers using handles from `gh pr view -c` (not display names).

**Required GitHub status checks (when branch protection is enabled):**

| Check name | Workflow | Purpose |
|------------|----------|---------|
| `bot-presence-gate` | `pr-bot-presence-gate.yml` | Waits until required bots (gemini, codex, sourcery) post + CI settled |
| `bot-feedback-gate` | `pr-bot-feedback-check.yml` | Review thread closure (implement / defer / decline) |

Apply protection: `npm run branch-protection:apply` (needs admin token). If API fails, see manual steps printed by that script or **Branch protection** below.

Do **not** squash merge until **both** required checks are green on GitHub — local `npm run wait-for-bots` alone is not sufficient when branch protection is active.

### 5. Bot wait trigger (dynamic)

```sh
npm run wait-for-bots
# optional: block until ready
npm run wait-for-bots -- --watch
# after @mentioning bots in the PR:
npm run wait-for-bots -- --bot-tag
```

Run this after creating a new PR (or after tagging bots). The script polls GitHub via `gh` and exits **2** while bots or CI are still active, **0** when ready, **1** on error or safety timeout.

**Ready when** (since the wait anchor — PR creation, or `--bot-tag` / `--since`):

- Required CI checks are not pending, **and**
- **Every required bot** has at least one review or issue comment since the anchor (default: **gemini**, **codex**, **sourcery**), **and**
- **90s** quiet window after the last bot activity, **and**
- At least **60s** since anchor

**Required bots (default):** `gemini` → `gemini-code-assist[bot]`, `codex` → `chatgpt-codex-connector[bot]`, `sourcery` → `sourcery-ai[bot]`. Override with `AR_BOT_WAIT_REQUIRED=gemini,codex,sourcery` or `npm run wait-for-bots -- --require-bots gemini,codex,sourcery`.

**Safety cap:** **28 minutes** from anchor. If required bots never post, exit **1** with **DO NOT MERGE** (not exit 0). Tune via env: `BOT_WAIT_POLL_SEC`, `BOT_WAIT_QUIET_SEC`, `BOT_WAIT_MIN_SEC`, `BOT_WAIT_MAX_MIN`.

**Forbidden:** squash merge while `wait-for-bots` exit **2** or **1**, or while `pr:bot-feedback-check` reports missing required bots.

**Orchestrator loop:** re-run until exit **0** (sleep ~45s between tries, or use `--watch`). Do **not** proceed to synthesis while exit **2**.

After tagging bots in PR comments or review replies, run `npm run wait-for-bots -- --bot-tag` then loop until exit **0**. Do **not** restart a wait cycle just because you pushed a code change. Fix-up pushes stay on the same branch and go straight to CI, feedback synthesis, and thread closure unless you tagged bots.

### 5b. Synthesize all feedback before responding

After `wait-for-bots` exits 0, and before replying to any thread:

1. Fetch ALL threads:
   - `gh pr view <n> --comments`
   - `gh api repos/<owner>/<repo>/pulls/<n>/reviews`
   - `gh api repos/<owner>/<repo>/pulls/<n>/comments`
   - On github.com: scan Conversation + Files until in-flight bot activity settles.
2. **Read every thread before replying to any of them.**
3. Post ONE `## Feedback plan` comment on the PR listing every thread with intended response:
   - implement (what and why) / defer (reason) / decline (reason)
   - Note any dependencies between items
4. Only after posting the plan: make code changes (single push), then reply in-thread to each bot.

### 6. Thread closure

Reply in-thread on GitHub for every substantive thread: `implemented in <sha>` / `deferred — <reason>` / `declined — <reason>`. If inline replies unavailable: `## Feedback responses` section in PR body. Do NOT merge with unanswered threads.

**Substantive thread:** an inline or review comment that proposes a code/doc change, reports a likely bug, or asks a blocking question. Exclude auto-generated summaries, reviewer guides, and low-signal one-liners (under ~40 characters, emoji-only, or “Useful? React with …” nudges). When in doubt, reply and resolve rather than skip.

**Automated gate (required before merge):**

```sh
npm run pr:bot-feedback-check -- --pr <n>
```

**Aggregate audit (all steps 4–7 gates):** `npm run pr:gates:check -- --pr <n>` — exit **0** only when CI, `wait-for-bots`, thread closure, GitHub `bot-*` checks, and `## Feedback plan` (when required) all pass. Invoke **pr-gates-agent** for read-only enforcement; **pr-fix-agent** for remediation.

Exit **1** when the PR has unresolved review threads or bot threads without an owner closure reply. `npm run ship:closeout:strict` runs this check when an open PR exists for the current branch. CI job **`bot-feedback-gate`** runs the same script on every PR event (with `--skip-bot-presence` because **`bot-presence-gate`** covers bot wait separately).

Do **not** `gh pr merge --squash` while the gate fails. If a PR merged early, run `npm run pr:bot-feedback-audit`, post in-thread replies on the merged PR, and open a scoped post-merge fix PR when code changes were skipped.

**Close without merge:** GitHub branch protection cannot block the "Close pull request" button. Agents must **not** close a PR without merge unless the user waives in writing. `npm run agent:auditor` fails on recently closed-unmerged PRs that still have open bot threads.

### 7. Merge

`gh pr merge --squash` — only after steps 5–6 **and**:

- GitHub required checks **`bot-presence-gate`** and **`bot-feedback-gate`** are green (when branch protection is enabled), **and**
- `npm run pr:bot-feedback-check -- --pr <n>` exit **0** locally (sanity check).

Do NOT enable auto-merge before thread closure if your repo uses CI-only auto-merge that bypasses bot replies.

### 8. Local server / assets confirmed

**There is no Cloudflare deploy for this repo.**

After merge to `main`:

- Restart or reload the **local CDR dashboard** so running code matches `main`:
  - `python cdr_dashboard_server.py --exports <path-to-latest-_exports>`  
  - Or use **`START_HERE.cmd`** / **`open_dashboard.cmd`** when that is how you normally launch.
- Ensure **`--site-root`** (if used) points at the AustralianRates **`site`** folder that contains **`foundation.css`** and ideally **`assets/banks/*.png`** (see `cdr_dashboard_server.py` auto-detection).
- Hard refresh the browser (cached `index.html` can reference stale script paths).

Push to `main` does **not** automatically update a long-lived local Python process — restart when needed.

**8b. Pi deploy (when merge touches dashboard, ingest, or Pi units)**

If the merge diff includes paths under `dashboard/`, `cdr_*.py`, `cdr_dashboard_server.py`, or `deploy/pi/`:

```sh
npm run pi:needs-deploy -- --ref origin/main~1
npm run pi:deploy:verify
```

If verify exits non-zero (drift or smoke failure) and the Pi git tree is clean:

```sh
npm run pi:deploy
```

Use Tailscale URL from `docs/UNIVERSAL_ROADMAP.md` via `AR_PI_BASE_URL` when not on the Pi.

**GitHub Actions (Pi):** every push to `main` runs `.github/workflows/pi-deploy-on-main.yml` (`python pi_deploy_verify.py --deploy` when `PI_SSH_PRIVATE_KEY` and `PI_SSH_HOST` secrets are set; skipped otherwise). Scheduled drift checks: `.github/workflows/pi-deploy-watchdog.yml`. Invoke **pi-deploy-watchdog** skill for detail.

**Actions secrets (repo Settings → Secrets → Actions):** `PI_SSH_PRIVATE_KEY`, `PI_SSH_HOST`; optional `PI_SSH_USER`. Optional variable `AR_PI_BASE_URL` (default `http://100.78.28.10:8808/`). Test deploy manually: Actions → **pi-deploy-on-main** → **Run workflow**.

### 9. Local verify

```sh
npm run verify:local -- --base-url=http://127.0.0.1:<port>/
```

Use the dashboard URL printed at server startup (port may not be 8808). From repo root. Report exit code.

For **UI** regressions (layout, logos, hierarchy, console errors), use **Browser MCP** (`user-browser_agent_cursor`) against that same base URL when the user requires it.

For workflow / verification-script changes, broaden checks manually (e.g. extra paths, ingest smoke) and document what you ran.

If exit non-zero: fix, restart server if needed, re-run until **0**.

---

## Closeout check (before claiming task done on a topic branch)

```sh
npm run ship:closeout:strict && npm run wait-for-bots
```

- `ship:closeout:strict` exit **2** → open PR still exists for this branch, **or** `pr:bot-feedback-check` failed; continue steps 5–9.
- `wait-for-bots` exit **2** → bots/CI not settled; sleep and re-run (or use `--watch`).

---

## Hard rules — urgency and tone never waive steps 5–7

Phrases that do NOT waive the wait gate, the synthesis step, or thread closure:

- "merge everything" / "batch merge" / "just merge" / "urgency" / "ASAP" / frustration
- "CI green" / "checks passed" while new-PR or bot-tag wait is still active, or threads are unsettled
- "no bot feedback" before `wait-for-bots` exits **0** for the current wait anchor (new PR or bot-tag)

Only an explicit written waiver for that specific PR waives bot closeout for that PR.

## Forbidden completions (while open PR exists and you have merge ability)

"done" / "shipped" / "dashboard verified" / "CI green so we're good" / "handing off the PR" / "merge-ready" without steps 5b–6 complete.

## After merge

`npm run git:graph-hygiene` (or `git fetch origin --prune`); delete local topic branch.

## Exception

`main` hotfix (user must explicitly request): push directly to `main`; still do steps **8–9** (local server + `verify:local`).

---

## Branch protection (GitHub)

Enforce merge gates on `main` so squash merge is blocked until bots respond and threads are closed.

```sh
npm run branch-protection:apply
```

Required status checks: **`bot-presence-gate`**, **`bot-feedback-gate`**. Also enables **`required_conversation_resolution`**.

If the API returns 403/404 (token lacks admin), apply manually:

1. Repo **Settings → Branches → Add branch protection rule**
2. Branch name pattern: `main`
3. **Require a pull request before merging** — ON (0 approvals OK unless you want human review)
4. **Require status checks to pass** — ON; **Require branches to be up to date** — ON
5. Required checks: `bot-presence-gate`, `bot-feedback-gate`
6. **Require conversation resolution before merging** — ON
7. **Do not allow bypassing** (recommended)

GitHub cannot block **Close pull request**; agents follow WORKFLOW.md step 6 close-without-merge policy and `npm run agent:auditor` catches violations.
