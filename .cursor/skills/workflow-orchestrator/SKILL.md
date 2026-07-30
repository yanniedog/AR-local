---
name: workflow-orchestrator
description: >-
  Single-pass workflow guardian: inspect git/PRs/transcripts, route actionable work,
  enforce one PR per task, and drive the WORKFLOW.md act-or-park ship bar.
---

# Workflow orchestrator

You are the **single-pass workflow guardian** for the current repository. You run as a **Cursor subagent** (or parent agent following this skill), act on reachable work, and park when only GitHub-owned CI is pending.

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
| Closeout | `npm run pr:arm-and-park -- --pr <n>` | Exit 3 = act; exit 2 = park |
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
- The universal protected review context **`bot-feedback-gate`** is green.
- `npm run wait-for-bots -- --pr <n>` is a single-shot required-CI settlement check. Gemini, Codex, Sourcery, CodeRabbit, Qwen/local LLM, and reviewer-presence checks are advisory.
- `npm run pr:bot-feedback-check -- --pr <n>` exits **0**: every substantive automated-review thread has an explicit disposition and is resolved.
- **Never** hand-roll `gh pr merge`. Use `pr:arm-and-park`, which refuses any base other than the exact default branch.
- **Never** close a PR without merge unless the user waives in writing; auditor fails on closed-unmerged PRs with open bot threads.

**After merge (step 7b ? before step 8):**

1. Branch from fresh `main`
2. Commit + push on topic branch only
3. `gh pr create --base main`
4. CI green
5. Run `npm run pr:arm-and-park -- --pr <n>` once. It marks drafts ready, arms auto-merge, returns **3** for actionable work and **2** for pending-only state. Never use agent watch/sleep loops.
5b. `## Feedback plan` then one push then in-thread replies
6. Thread closure ? every **substantive** inline thread (bot or human) gets in-thread implement/defer/decline; resolve GitHub threads before merge. **Substantive** = file-level inline comment, P1/P2 bot finding, CI failure tied to the PR, or any thread proposing a code/doc change (exclude pure summary-only bot posts).
7. `npm run pr:bot-feedback-check -- --pr <n>` ? exit non-zero blocks merge
8. `npm run pr:arm-and-park -- --pr <n>` owns merge progression. Exit **0** means ready or merged, **2** means parked, and **3** means fix the reported CI/base/conflict/thread state.
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
2. Worker owns that PR through synthesis (5b) → thread closure → a single-shot `pr:gates:check` → squash merge or park.
3. Orchestrator **does not** close threads or merge on behalf of multiple PRs in one turn — it ensures every PR has its worker and tracks blockers.

Parallel pr-fix workers: allowed for **disjoint** PR numbers only. Never two writers on the same PR.

## Orchestrator loop

```
SCAN → PLAN → DELEGATE (pr-fix per PR + path owners) → (subagents run) → SCAN → …
```

**Closeout before idle claim:**

```sh
npm run ship:closeout:strict
npm run pr:arm-and-park -- --pr <n>
npm run close-loop:check -- --post-merge-gap   # on main after merges
```

These are single-shot audits. Do not use `--watch` or a sleep-poll loop.

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
