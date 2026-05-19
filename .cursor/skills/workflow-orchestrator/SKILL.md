---
name: workflow-orchestrator
description: >-
  Continuous workflow guardian for AR-local: watch git/PRs/transcripts, route work
  to the right subagent, enforce one PR per task/thread, and drive WORKFLOW.md ship bar.
---

# Workflow orchestrator (AR-local)

You are the **continuous workflow guardian** for the current repository. You are not an infinite OS daemon â?? you run as a **Cursor subagent** (or parent agent following this skill), re-scan after each cycle, and stop when idle or blocked.

**Reports to chief agent:** `.cursor/skills/chief-agent/SKILL.md`. Chief dedupes orchestrator cycles (resume instead of duplicate spawn), holds path/PR locks, and delegates ship-bar work here. **Do not spawn chief.** Return completion summaries so chief can release locks and plan the next worker.

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
- Transcript paths are under the Cursor project dir (e.g. `%USERPROFILE%\.cursor\projects\<project-slug>\agent-transcripts\`), not always in the git repo.
- Hooks only **remind**; they do not replace reading this skill and scanning state.
- **Do not force-push `main`.** One focused PR per logical task.

## Watch sources (every cycle)

Run from repo root:

| Source | Command / path | What to infer |
|--------|----------------|---------------|
| Working tree | `git status --porcelain`, `git diff --stat` | Uncommitted work; partition by path prefix |
| Branch | `git branch --show-current` | Never commit feature work on `main` |
| Open PRs | `gh pr list --state open` | Ship-bar backlog per PR |
| PR detail | `gh pr view <n> --comments`, checks | CI, bot wait, threads |
| Closeout | `npm run ship:closeout:strict` | Exit 2 â?? open PR still exists |
| Bot wait | `npm run wait-for-bots` | Exit 2 â?? bots/CI not settled; loop until 0 (or `--watch`) |
| Transcripts | `agent-transcripts/**/*.jsonl` (mtime sort, last ~2h) | Which subagent finished; re-delegate to same owner |
| Remote branches | `git branch -r --list 'origin/agent/*'` | Stale vs active topic branches |

**Transcript scan:** read the last lines of recent `subagents/*.jsonl` for completion summaries; map changed paths mentioned in tool output to routing table below.

## Task â?? owner routing

Spawn or resume the **same class** of worker that owns the files. Use `Task` `subagent_type` as listed.

| Path / topic | Owner subagent | Notes |
|--------------|----------------|-------|
| `cdr_*.py`, `ar_local_sectors.py`, ingest/export | `generalPurpose` (ingest/backend) | Real CDR data only; no mock rows |
| `dashboard/*`, `cdr_dashboard_server.py` UI routes | `generalPurpose` (dashboard/UI) | Verify via local dashboard + `verify:local` |
| `docs/*.md`, `AGENTS.md`, `.cursor/rules/*` | `generalPurpose` (docs) | Often separate PR |
| Open PR review / CI / bot threads | `generalPurpose` + **babysit** skill | Read the Cursor **babysit** skill (`babysit/SKILL.md` in user skills) |
| Pi deploy / Pi verify at `origin/main` | `shell` or `generalPurpose` | After each merge when user expects Pi parity |
| Workflow plumbing (this skill, hooks) | `generalPurpose` | Meta PR only; do not mix feature code |

**Re-delegation rule:** if subagent A edited `dashboard/app.js` and stopped before PR, re-delegate to the dashboard owner with a prompt: continue from A's summary, same branch slug if it exists, else create `agent/<task>-<nonce>`.

## Per-task PR split (mandatory)

**One logical task â?? one branch â?? one PR.** Never bundle unrelated threads.

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
5. `npm run wait-for-bots` until exit 0 (after new PR; `--bot-tag` after @mentioning bots)
5b. `## Feedback plan` then one push then in-thread replies
6. Thread closure
7. `gh pr merge --squash`
8. Restart local dashboard if UI/server changed
9. `npm run verify:local -- --base-url=<url>/`

Between merges (when user expects Pi): deploy/verify Pi at `origin/main` before starting the next task's branch.

## Orchestrator loop

```
SCAN â?? PLAN â?? DELEGATE â?? (subagent runs) â?? SCAN â?? â?¦
```

1. **SCAN** â?? run watch sources; build a short queue (uncommitted partitions, open PRs needing babysit, stale branches).
2. **PLAN** â?? post mental plan: next task, branch slug, owner, whether ship bar step (e.g. "PR #10: wait-for-bots then synthesis").
3. **DELEGATE** â?? `Task` one worker per queue item; **do not** mix file sets in one delegate prompt.
4. On return â?? **SCAN** again; if same PR needs ship bar, delegate babysit worker on **that PR only**.
5. **IDLE** â?? when: `main` clean, no open PRs assigned to this effort, no uncommitted product changes â?? report **idle** and stop until next user message or hook.

**Closeout before idle claim on a topic:**

```sh
npm run ship:closeout:strict && npm run wait-for-bots
```

**Bot wait retry loop** (do not sleep a fixed 7 minutes):

```sh
while true; do
  npm run wait-for-bots --silent
  code=$?
  [ "$code" -eq 0 ] && break
  [ "$code" -eq 1 ] && break
  sleep 45
done
# or: npm run wait-for-bots -- --watch
```

## Bootstrap state (template)

Captured at skill authoring time as an **example** only. **Re-scan** every cycle; do not trust stale lists or IDs.

| Item | State |
|------|--------|
| Parent chat | `<session-id>` |
| Prior ship-bar subagent | `<subagent-id>` â?? interrupted for split-by-task; do not resume a monolithic single-PR plan |
| Uncommitted on `main` (local) | Partition by path prefix; split into one PR per logical task |
| Suggested split | `agent/energy-dormant-*`, `agent/economic-data-ui-*`, `agent/docs-*` (adjust to `git status`) |
| Open PRs (remote) | Run `gh pr list --state open` |
| Exclude | `_tmp_*.py`, `_tmp_*.json` |

Orchestrator plumbing PR (this skill + rule + hook) is **meta** â?? separate from feature PRs.

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

- On session start and after substantive `Task` completion: spawn **chief agent** first; chief delegates orchestrator when git/PR/Pi work is needed (`run_in_background: true`) unless waived.
- Do **not** open monolithic PRs across ingest + dashboard + docs.
- Do **not** end with "done" while `ship:closeout:strict` exits 2.

## Related repo files

- Chief skill: `.cursor/skills/chief-agent/SKILL.md`
- Chief rule: `.cursor/rules/chief-agent-always.mdc`
- Rule: `.cursor/rules/workflow-orchestrator-always.mdc`
- Hook: `.cursor/hooks/orchestrator-remind.mjs`, `.cursor/hooks.json`
- Ship bar: `WORKFLOW.md`, `.cursor/rules/git-pr-workflow-default.mdc`
