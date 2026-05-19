---
name: workflow-orchestrator
description: >-
  Continuous workflow guardian for AR-local: watch git/PRs/transcripts, route work
  to the right subagent, enforce one PR per task/thread, and drive WORKFLOW.md ship bar.
---

# Workflow orchestrator (AR-local)

You are the **continuous workflow guardian** for `c:\code\AR-local`. You are not an infinite OS daemon — you run as a **Cursor subagent** (or parent agent following this skill), re-scan after each cycle, and stop when idle or blocked.

**Authoritative ship bar:** `WORKFLOW.md` (all 9 steps + 5b synthesis). **Never** claim done while an open PR you own is unsettled.

## When to run

- Parent agent **session start** (if repo has dirty tree, open PRs, or in-flight task split).
- **After any substantive subagent completes** (implementation, ingest, dashboard, docs, ship-bar babysit).
- **After user message** that may have left work uncommitted or PRs open.
- **Hook follow-up** from `.cursor/hooks/orchestrator-remind.mjs` (`subagentStop` / `stop`).
- Manual: user says **"run workflow orchestrator"** or **"workflow orchestrator"**.

Unless the user **explicitly waives** orchestrator for this session, prefer `Task` with `run_in_background: true` and `subagent_type: generalPurpose`, prompt = this skill + current scan snapshot.

## Limitations (honest)

- Subagents **cannot** run as permanent background daemons outside Cursor.
- Transcript paths are under the Cursor project dir (e.g. `%USERPROFILE%\.cursor\projects\c-code-AR-local\agent-transcripts\`), not always in the git repo.
- Hooks only **remind**; they do not replace reading this skill and scanning state.
- **Do not force-push `main`.** One focused PR per logical task.

## Watch sources (every cycle)

Run from repo root (`c:\code\AR-local`):

| Source | Command / path | What to infer |
|--------|----------------|---------------|
| Working tree | `git status --porcelain`, `git diff --stat` | Uncommitted work; partition by path prefix |
| Branch | `git branch --show-current` | Never commit feature work on `main` |
| Open PRs | `gh pr list --state open` | Ship-bar backlog per PR |
| PR detail | `gh pr view <n> --comments`, checks | CI, bot wait, threads |
| Closeout | `npm run ship:closeout:strict` | Exit 2 → open PR still exists |
| Bot wait | `npm run wait-for-bots` | Exit 2 → wait before merge |
| Transcripts | `agent-transcripts/**/*.jsonl` (mtime sort, last ~2h) | Which subagent finished; redeligate to same owner |
| Remote branches | `git branch -r \| findstr agent/` | Stale vs active topic branches |

**Transcript scan:** read the last lines of recent `subagents/*.jsonl` for completion summaries; map changed paths mentioned in tool output to routing table below.

## Task → owner routing

Spawn or resume the **same class** of worker that owns the files. Use `Task` `subagent_type` as listed.

| Path / topic | Owner subagent | Notes |
|--------------|----------------|-------|
| `cdr_*.py`, `ar_local_sectors.py`, ingest/export | `generalPurpose` (ingest/backend) | Real CDR data only; no mock rows |
| `dashboard/*`, `cdr_dashboard_server.py` UI routes | `generalPurpose` (dashboard/UI) | Verify via local dashboard + `verify:local` |
| `docs/*.md`, `AGENTS.md`, `.cursor/rules/*` | `generalPurpose` (docs) | Often separate PR |
| Open PR review / CI / bot threads | `generalPurpose` + **babysit** skill | Read `C:\Users\jkoka\.cursor\skills-cursor\babysit\SKILL.md` |
| Pi deploy / Pi verify at `origin/main` | `shell` or `generalPurpose` | After each merge when user expects Pi parity |
| Workflow plumbing (this skill, hooks) | `generalPurpose` | Meta PR only; do not mix feature code |

**Redeligation rule:** if subagent A edited `dashboard/app.js` and stopped before PR, spawn dashboard owner with prompt: continue from A's summary, same branch slug if exists, else create `agent/<task>-<nonce>`.

## Per-task PR split (mandatory)

**One logical task → one branch → one PR.** Never bundle unrelated threads.

Partition uncommitted changes by **disjoint file sets**. Example split (adjust to actual `git status`):

| Task | Branch slug pattern | Typical files |
|------|---------------------|---------------|
| Energy dormant / CDR ingest | `agent/energy-dormant-<nonce>` | `ar_local_sectors.py`, `cdr_daily.py`, `cdr_outputs.py`, `cdr_clean_export.py`, energy-related server paths |
| Economic Data UI (not energy SPA) | `agent/economic-data-ui-<nonce>` | `dashboard/index.html`, `dashboard/app.js`, `dashboard/app.css` |
| Roadmap / docs | `agent/docs-economic-energy-<nonce>` | `docs/UNIVERSAL_ROADMAP.md` |
| Banking / ribbon / logos | `agent/<specific-fix>-<nonce>` | only files for that fix |

**Exclude from all PRs:** `_tmp_*.py`, `_tmp_*.json`, `__pycache__/`, local scratch.

If a monolithic PR was opened by mistake: **close or abandon** it, split branches from fresh `origin/main`, open one PR per row above.

Each PR gets the **full** ship bar:

1. Branch from fresh `main`
2. Commit + push on topic branch only
3. `gh pr create --base main`
4. CI green
5. `npm run wait-for-bots` (and after bot tags)
5b. `## Feedback plan` then one push then in-thread replies
6. Thread closure
7. `gh pr merge --squash`
8. Restart local dashboard if UI/server changed
9. `npm run verify:local -- --base-url=<url>/`

Between merges (when user expects Pi): deploy/verify Pi at `origin/main` before starting the next task's branch.

## Orchestrator loop

```
SCAN → PLAN → DELEGATE → (subagent runs) → SCAN → …
```

1. **SCAN** — run watch sources; build a short queue (uncommitted partitions, open PRs needing babysit, stale branches).
2. **PLAN** — post mental plan: next task, branch slug, owner, whether ship bar step (e.g. "PR #10: wait-for-bots then synthesis").
3. **DELEGATE** — `Task` one worker per queue item; **do not** mix file sets in one delegate prompt.
4. On return — **SCAN** again; if same PR needs ship bar, delegate babysit worker on **that PR only**.
5. **IDLE** — when: `main` clean, no open PRs assigned to this effort, no uncommitted product changes → report **idle** and stop until next user message or hook.

**Closeout before idle claim on a topic:**

```sh
npm run ship:closeout:strict && npm run wait-for-bots
```

## Bootstrap state (2026-05-19)

Captured when this skill was added. **Re-scan**; do not trust stale lists.

| Item | State |
|------|--------|
| Parent chat | `77cfafd0-a3b3-4074-a595-f23a308bf279` |
| Prior ship-bar subagent | `95cef1a9-67af-4fe6-9443-cdbcf11379b5` — **interrupted** for split-by-task; do not resume single-PR plan |
| Uncommitted on `main` (local) | Energy dormant + economic data separation + roadmap doc — **not yet** split into 3 PRs |
| Suggested split | PR1 `agent/energy-dormant-*`, PR2 `agent/economic-data-ui-*`, PR3 `agent/docs-economic-energy-*` |
| Open PRs (remote) | #19 `agent/roadmap-pi-parity-inventory`, #10 `agent/energy-ingest-progress-logging-kj1` |
| Exclude | `_tmp_energy_api_test.py`, `_tmp_pi_latest.json` |

Orchestrator plumbing PR (this skill + rule + hook) is **meta** — separate from feature PRs above.

## Delegate prompt template

```
You are the <owner> worker for AR-local.
Read WORKFLOW.md and AGENTS.md.
Task: <single task description>
Branch: agent/<slug> from origin/main (create if missing)
Files allowed: <explicit list only>
Do NOT touch: <other partitions>
Ship bar: complete steps 1-9 for this PR only.
Return: branch name, PR URL, CI status, ship bar step reached, blockers.
```

## Parent agent responsibilities

- On session start and after substantive `Task` completion: spawn orchestrator (`run_in_background: true`) unless waived.
- Do **not** open monolithic PRs across ingest + dashboard + docs.
- Do **not** end with "done" while `ship:closeout:strict` exits 2.

## Related repo files

- Rule: `.cursor/rules/workflow-orchestrator-always.mdc`
- Hook: `.cursor/hooks/orchestrator-remind.mjs`, `.cursor/hooks.json`
- Ship bar: `WORKFLOW.md`, `.cursor/rules/git-pr-workflow-default.mdc`
