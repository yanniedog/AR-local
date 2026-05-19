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
- At least one configured bot has commented since the anchor, **and**
- Either no bot activity for **90s** (quiet window) **or** every configured bot account has posted, **and**
- At least **60s** since anchor (unless a prior successful wait is cached for this PR)

**Safety cap:** **28 minutes** from anchor (exit **1** if exceeded). Tune via env: `BOT_WAIT_POLL_SEC`, `BOT_WAIT_QUIET_SEC`, `BOT_WAIT_MIN_SEC`, `BOT_WAIT_MAX_MIN`, `BOT_WAIT_LOGINS`.

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

### 7. Merge

`gh pr merge --squash` — only after steps 5–6. Do NOT enable auto-merge before thread closure if your repo uses CI-only auto-merge that bypasses bot replies.

### 8. Local server / assets confirmed

**There is no Cloudflare deploy for this repo.**

After merge to `main`:

- Restart or reload the **local CDR dashboard** so running code matches `main`:
  - `python cdr_dashboard_server.py --exports <path-to-latest-_exports>`  
  - Or use **`START_HERE.cmd`** / **`open_dashboard.cmd`** when that is how you normally launch.
- Ensure **`--site-root`** (if used) points at the AustralianRates **`site`** folder that contains **`foundation.css`** and ideally **`assets/banks/*.png`** (see `cdr_dashboard_server.py` auto-detection).
- Hard refresh the browser (cached `index.html` can reference stale script paths).

Push to `main` does **not** automatically update a long-lived local Python process — restart when needed.

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

- `ship:closeout:strict` exit **2** → open PR still exists for this branch; continue steps 5–9.
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
