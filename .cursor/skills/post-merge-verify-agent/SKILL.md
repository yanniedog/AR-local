---
name: post-merge-verify-agent
description: >-
  After merge: restart local dashboard, npm run verify:local, optional Pi check,
  screenshot evidence. WORKFLOW.md steps 8-9.
---

# Post-merge verify agent (AR-local)

You execute **`WORKFLOW.md` steps 8–9** after code is on `main` — local server matches merged tree, HTTP smoke passes, optional Pi probe and browser evidence.

You **do not** merge PRs or reply to review threads (→ **pr-fix-agent**, **workflow-orchestrator**).

**Reports to:** chief agent. Required for close-loop: `npm run close-loop:check -- --post-merge-gap`.

## Invocation phrases

- **"run post-merge verify"**
- Chief/orchestrator after step 7 merge: *Follow `.cursor/skills/post-merge-verify-agent/SKILL.md` for PR #N.*

## Path locks

| Allowed | Forbidden |
|---------|-----------|
| Restart local dashboard process; run npm/python verify commands | Feature edits on `main` without new branch |
| Delegate **pi-deploy-agent** for Pi sync | Claiming verify without exit code |
| Browser MCP screenshots (read-only) | Skipping verify when dashboard/server changed |

## When to run

- Immediately after squash merge to `main`.
- Chief `close-loop:check` flags missing verify on recent merge.
- User asks for post-merge sign-off evidence.

## Step 8 — Local server / assets

From fresh `main`:

```sh
git fetch origin && git checkout main && git pull origin main
```

Restart dashboard so running code matches `main`:

```powershell
python cdr_dashboard_server.py --exports <path-to-latest-_exports> --runs runs --host 127.0.0.1 --port 8808 --site-root C:\code\australianrates\site --preload
```

Or **`START_HERE.cmd`** / **`open_dashboard.cmd`** if that is the user’s normal launcher.

- Confirm `--site-root` has `foundation.css` and ideally `assets/banks/*.png`.
- Hard-refresh browser if cached `index.html` references stale scripts.

If only non-dashboard files merged, document skip rationale — still run `verify:local` when server or static dashboard paths changed.

## Step 9 — Local verify

```sh
npm run verify:local -- --base-url=http://127.0.0.1:<port>/
```

Use port from server stdout (often `8808`). **Exit code must be 0** unless user waived in writing.

Loop: fix on topic branch → PR → merge → repeat 8–9 until 0.

## Optional Pi verify

When merge affects runtime on Pi, delegate or run:

1. **pi-deploy-agent** — pull `main`, restart units, `http://100.78.28.10:8808/api/latest`
2. Pi-local: `npm run verify:local -- --base-url=http://127.0.0.1:8808/` over SSH

## Optional UI evidence

When user/chief requires UI proof (not replacing HTTP smoke):

- **deep-browser-explore** — functional pass on local URL
- **parity-agent** — only if task was explicit prod comparison

Minimal evidence: landing screenshot + `/api/latest` JSON snippet (run_date, keys).

## Close-loop commands

```sh
npm run close-loop:check -- --pr <n>
npm run close-loop:check -- --post-merge-gap
```

Exit **1** → chief opens follow-up PR in same cycle; do not report “merged and done”.

## Return format

| Check | Result |
|-------|--------|
| main SHA | short |
| Server restarted | yes/no |
| verify:local | exit code + URL |
| Pi /api/latest | optional status |
| Screenshots | paths |
| close-loop:check | exit code |

## Anti-patterns

- “Merged” without verify exit 0 when dashboard/server changed.
- Using www.australianrates.com as acceptance URL.
- Leaving long-lived Python process on pre-merge code.

## Related

- `WORKFLOW.md` steps 8–9
- `pi-deploy-agent` — Pi runtime sync
- `deep-browser-explore` — supplemental UI QA
- `dashboard-agent` — fixes if verify fails
