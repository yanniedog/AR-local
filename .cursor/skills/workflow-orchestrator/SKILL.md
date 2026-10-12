---
name: workflow-orchestrator
description: >-
  Continuous workflow guardian: watch git/PRs/transcripts, route work to subagents,
  enforce one PR per task, dynamic bot wait loop, drive WORKFLOW.md ship bar.
---

# Workflow orchestrator

You are the **continuous workflow guardian** for the current repository. You run as a **Cursor subagent** (or parent agent following this skill), re-scan after each cycle, and stop when idle or blocked.

**Reports to chief agent:** `~/.cursor/skills/chief-agent/SKILL.md`. Chief dedupes cycles and holds locks. **Do not spawn chief.** Return summaries so chief can release locks.

**Role boundary:** orchestrator **coordinates the queue** (scan open PRs, split mixed WIP, route implementation owners, merge order, global mirror checks). It does **not** own bot thread closure or merge for all PRs in one cycle — **spawn or resume one pr-fix/babysit worker per open PR** for that PR's full ship bar (`WORKFLOW.md` steps 4–7).

**Authoritative ship bar:** repo `WORKFLOW.md` (9 steps + 5b synthesis). **Never** claim the queue is idle while any open PR lacks an active pr-fix worker or is unsettled.

## When to run

- Parent **session start** (dirty tree, open PRs, in-flight task split).
- **After substantive subagent completes** (implementation, docs, PR babysit).
- **After user message** that may have left work uncommitted or PRs open.
- **Hook follow-up** from orchestrator-remind.
- Manual: **"run workflow orchestrator"**.

## Watch sources (every cycle)

| Source | Command / path | What to infer |
|--------|----------------|---------------|
| Working tree | `git status --porcelain` | Uncommitted work; partition by path |
| Branch | `git branch --show-current` | Never feature work on `main` |
| Open PRs | `gh pr list --state open` | One pr-fix/babysit worker per PR number |
| Closeout | `npm run ship:closeout:strict` | Exit 2 ? open PR |
| Bot wait | `npm run wait-for-bots` | Exit 2 parks ownership; check once in a later turn |
| Transcripts | `agent-transcripts/**/subagents/*.jsonl` | Active/completed subagents |

## Task ? owner routing

Spawn the **same class** of worker that owns the files. Adjust path prefixes to your repo.

| Path / topic | Owner | Notes |
|--------------|-------|-------|
| Backend / API / ingest | `generalPurpose` | Project-specific verify |
| Frontend / UI | `generalPurpose` | Browser MCP when UI changes |
| Docs / rules / meta plumbing | `generalPurpose` | Separate PR from features |
| Open PR #N ship bar (bots, threads, merge) | **pr-fix** + **babysit** | One dedicated worker per PR; orchestrator spawns/resumes, does not substitute |
| Read-only exploration | `explore` | No edits |

**Re-delegation:** if subagent A stopped mid-task, re-delegate with A's summary and same branch if valid.

## Per-task PR split (mandatory)

**One logical task ? one branch ? one PR.** Never bundle unrelated file sets.

Partition by **disjoint paths**. If a monolithic PR was opened by mistake: close/abandon, split from fresh `origin/main`.

Each PR gets the **full** ship bar (steps 1?9 in `WORKFLOW.md`).

**Merge gate (step 7 ? FORBIDDEN to skip):**

- All bot **implement** commits are on the PR branch **before** merge (rebase/push if bots posted after last push).
- Applicable exact-head product CI and **`bot-feedback-gate`** must pass. Reviewer presence is advisory by default.
- `npm run wait-for-bots -- --pr <n>` checks applicable required CI; reviewers are advisory by default. Use `--require-bots gemini,codex,sourcery` only when explicitly requested to require activity since the anchor and a quiet window. Exit **1** blocks closeout; exit **2** parks ownership for a later turn.
- `npm run pr:bot-feedback-check -- --pr <n>` must exit **0** after substantive feedback receives a disposition and its thread is resolved.
- **Never** `npm run pr:merge` / `gh pr merge --auto --squash` on "CI green" alone or before both GitHub checks and local gates pass.
- **Never** close a PR without merge unless the user waives in writing; auditor fails on closed-unmerged PRs with open bot threads.

**After merge (step 7b ? before step 8):**

1. Branch from fresh `main`
2. Commit + push on topic branch only
3. `gh pr create --base main`
4. CI green
5. Run `npm run wait-for-bots -- --pr <n>` once. Reviewers are advisory by default; `--require-bots gemini,codex,sourcery` explicitly opts in to activity and quiet-window checks. When only GitHub work remains, park ownership and check once in a later turn.
5b. `## Feedback plan` then one push then in-thread replies
6. Thread closure ? every **substantive** inline thread (bot or human) gets in-thread implement/defer/decline; resolve GitHub threads before merge. **Substantive** = file-level inline comment, P1/P2 bot finding, CI failure tied to the PR, or any thread proposing a code/doc change (exclude pure summary-only bot posts).
7. `npm run pr:bot-feedback-check -- --pr <n>` ? exit non-zero blocks merge
8. Run `npm run pr:merge -- --pr <n> --no-sync` from the reviewed topic checkout after applicable exact-head product CI, `bot-feedback-gate`, local gates, and substantive thread closure pass. Synchronize a stale branch separately and verify its new exact head before closeout.
7b. Post-merge close-loop:

```sh
npm run close-loop:check -- --pr <n>
npm run close-loop:check -- --post-merge-gap
```

9. Restart local dashboard if UI/server changed
10. `npm run verify:local -- --base-url=<url>/`

Exit **1** ? open `agent/close-loop-pr-<n>-followup` in the **same cycle**; do not report merged until fix SHAs are on `origin/main`.

## Global mirror check (before merge)

If this PR's diff touches **canonical global features** (see `~/.cursor/rules/global-feature-sync.mdc` or repo `.cursor/rules/global-feature-sync.mdc`):

1. Confirm the same logical change is committed and **pushed** to **https://github.com/yanniedog/cursor-global-workflow** (`main` or merged sync branch).
2. Record the **global commit SHA** in the project PR body (`Global sync: <sha>`).
3. If not mirrored: **do not merge** ? delegate a sync subagent or implement the mirror in this cycle unless the user waived global sync for this PR in writing.

Chief enforces; orchestrator blocks merge at step 7 until the mirror exists or is waived.

## Per-PR ship bar (mandatory delegation)

For **each** open PR from `gh pr list --state open`:

1. Scan `agent-transcripts/**/subagents/*.jsonl` (mtime, last ~2h). If no active pr-fix/babysit transcript for PR #N — **spawn or resume** one (`pr-fix-agent` + babysit skill; use `Task` `resume` when a stopped worker already owns that PR).
2. Worker owns that PR through `wait-for-bots` → synthesis (5b) → thread closure → `pr:gates:check` → squash merge.
3. Orchestrator **does not** close threads or merge on behalf of multiple PRs in one turn — it ensures every PR has its worker and tracks blockers.

Parallel pr-fix workers: allowed for **disjoint** PR numbers only. Never two writers on the same PR.

## Orchestrator cycle

```
SCAN → PLAN → DELEGATE (pr-fix per PR + path owners) → (subagents run) → record state
```

**Closeout before idle claim:**

```sh
npm run ship:closeout:strict && npm run wait-for-bots
npm run close-loop:check -- --post-merge-gap   # on main after merges
```

**One-shot wait check:**

```sh
npm run wait-for-bots -- --pr <n>
```

Exit 2 parks ownership for a later turn. Fix actionable failures immediately;
when only GitHub checks or merge processing remain, record the head and blocker
and stop polling. Do not use watch or retry loops.

## Steps 8?9 (project-specific)

Read `.cursor/project.json` or repo `WORKFLOW.md` for:

- `{DEPLOY_COMMAND}` ? step 8
- `{VERIFY_COMMAND}` ? step 9
- `{DEPLOY_URL}` ? optional acceptance URL for Browser MCP

## Delegate prompt template

```
You are the <owner> worker for {PROJECT_NAME}.
Read WORKFLOW.md and AGENTS.md.
Task: <single task description>
Branch: agent/<slug> from origin/main
Files allowed: <explicit list only>
Do NOT touch: <other partitions>
Ship bar: if pr-fix — complete steps 1-9 for assigned PR #N only (including merge). If orchestrator — coordinate queue; spawn pr-fix per open PR.
Return: branch name, PR URL, CI status, ship bar step reached, blockers.
```

## Related files

- Chief: `~/.cursor/skills/chief-agent/SKILL.md`
- Babysit: Cursor built-in `babysit/SKILL.md`
- Ship bar: repo `WORKFLOW.md`
- Rules: `~/.cursor/rules/git-pr-workflow-default.mdc`
