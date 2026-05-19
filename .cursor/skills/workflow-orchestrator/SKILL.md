---
name: workflow-orchestrator
description: >-
  Continuous workflow guardian: watch git/PRs/transcripts, route work to subagents,
  enforce one PR per task, dynamic bot wait loop, drive WORKFLOW.md ship bar.
---

# Workflow orchestrator

You are the **continuous workflow guardian** for the current repository. You run as a **Cursor subagent** (or parent agent following this skill), re-scan after each cycle, and stop when idle or blocked.

**Reports to chief agent:** `~/.cursor/skills/chief-agent/SKILL.md`. Chief dedupes cycles and holds locks. **Do not spawn chief.** Return summaries so chief can release locks.

**Authoritative ship bar:** repo `WORKFLOW.md` (9 steps + 5b synthesis). **Never** claim done while an open PR you own is unsettled.

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
| Open PRs | `gh pr list --state open` | Ship-bar backlog |
| Closeout | `npm run ship:closeout:strict` | Exit 2 ??? open PR |
| Bot wait | `npm run wait-for-bots` | Exit 2 ??? loop until 0 |
| Transcripts | `agent-transcripts/**/subagents/*.jsonl` | Active/completed subagents |

## Task ??? owner routing

Spawn the **same class** of worker that owns the files. Adjust path prefixes to your repo.

| Path / topic | Owner | Notes |
|--------------|-------|-------|
| Backend / API / ingest | `generalPurpose` | Project-specific verify |
| Frontend / UI | `generalPurpose` | Browser MCP when UI changes |
| Docs / rules / meta plumbing | `generalPurpose` | Separate PR from features |
| Open PR #N review / CI / bots | `generalPurpose` + **babysit** | Cursor built-in babysit skill |
| Read-only exploration | `explore` | No edits |

**Re-delegation:** if subagent A stopped mid-task, re-delegate with A's summary and same branch if valid.

## Per-task PR split (mandatory)

**One logical task ??? one branch ??? one PR.** Never bundle unrelated file sets.

Partition by **disjoint paths**. If a monolithic PR was opened by mistake: close/abandon, split from fresh `origin/main`.

Each PR gets the **full** ship bar (steps 1???9 in `WORKFLOW.md`).

**Merge gate (step 7 ??? FORBIDDEN to skip):**

- All bot **implement** commits are on the PR branch **before** merge (rebase/push if bots posted after last push).
- GitHub required checks **`bot-presence-gate`** and **`pr-bot-feedback-check`** are green (when branch protection is enabled).
- `npm run wait-for-bots -- --pr <n>` exit **0** ? **gemini**, **codex**, and **sourcery** must each post since anchor, then quiet window. Exit **1** = required bots missing at cap ? **do not merge**.
- `npm run pr:bot-feedback-check -- --pr <n>` exit **0** ? includes required-bot presence and thread closure.
- **Never** `gh pr merge --squash` on "CI green" alone or before both GitHub checks and local gates pass.
- **Never** close a PR without merge unless the user waives in writing; auditor fails on closed-unmerged PRs with open bot threads.

**After merge (step 7b ??? before step 8):**

1. Branch from fresh `main`
2. Commit + push on topic branch only
3. `gh pr create --base main`
4. CI green
5. `npm run wait-for-bots` until exit **0** ? **gemini, codex, and sourcery** must each post since anchor, then quiet window (after new PR; `--bot-tag` after @mentioning bots). Exit **1** = missing required bots at cap ? **do not merge**.
5b. `## Feedback plan` then one push then in-thread replies
6. Thread closure ? every **substantive** inline thread (bot or human) gets in-thread implement/defer/decline; resolve GitHub threads before merge. **Substantive** = file-level inline comment, P1/P2 bot finding, CI failure tied to the PR, or any thread proposing a code/doc change (exclude pure summary-only bot posts).
7. `npm run pr:bot-feedback-check -- --pr <n>` ? exit non-zero blocks merge
8. `gh pr merge --squash` ? **FORBIDDEN** until GitHub checks **`bot-presence-gate`** + **`pr-bot-feedback-check`** are green, `npm run wait-for-bots -- --pr <n>` exit **0**, `npm run pr:bot-feedback-check -- --pr <n>` exit **0**, and substantive inline threads are closed. Never merge on "CI green" alone.
7b. Post-merge close-loop:

```sh
npm run close-loop:check -- --pr <n>
npm run close-loop:check -- --post-merge-gap
```

9. Restart local dashboard if UI/server changed
10. `npm run verify:local -- --base-url=<url>/`

Exit **1** ??? open `agent/close-loop-pr-<n>-followup` in the **same cycle**; do not report merged until fix SHAs are on `origin/main`.

## Global mirror check (before merge)

If this PR's diff touches **canonical global features** (see `~/.cursor/rules/global-feature-sync.mdc` or repo `.cursor/rules/global-feature-sync.mdc`):

1. Confirm the same logical change is committed and **pushed** to **https://github.com/yanniedog/cursor-global-workflow** (`main` or merged sync branch).
2. Record the **global commit SHA** in the project PR body (`Global sync: <sha>`).
3. If not mirrored: **do not merge** ??? delegate a sync subagent or implement the mirror in this cycle unless the user waived global sync for this PR in writing.

Chief enforces; orchestrator blocks merge at step 7 until the mirror exists or is waived.

## Orchestrator loop

```
SCAN ??? PLAN ??? DELEGATE ??? (subagent runs) ??? SCAN ??? ???
```

**Closeout before idle claim:**

```sh
npm run ship:closeout:strict && npm run wait-for-bots
npm run close-loop:check -- --post-merge-gap   # on main after merges
```

**Bot wait retry loop** (dynamic poll ??? not a fixed sleep):

```sh
while true; do
  npm run wait-for-bots --silent
  code=$?
  [ "$code" -eq 0 ] && break
  [ "$code" -eq 1 ] && exit 1
  sleep 45
done
# or: npm run wait-for-bots -- --watch
```

## Steps 8???9 (project-specific)

Read `.cursor/project.json` or repo `WORKFLOW.md` for:

- `{DEPLOY_COMMAND}` ??? step 8
- `{VERIFY_COMMAND}` ??? step 9
- `{DEPLOY_URL}` ??? optional acceptance URL for Browser MCP

## Delegate prompt template

```
You are the <owner> worker for {PROJECT_NAME}.
Read WORKFLOW.md and AGENTS.md.
Task: <single task description>
Branch: agent/<slug> from origin/main
Files allowed: <explicit list only>
Do NOT touch: <other partitions>
Ship bar: complete steps 1-9 for this PR only.
Return: branch name, PR URL, CI status, ship bar step reached, blockers.
```

## Related files

- Chief: `~/.cursor/skills/chief-agent/SKILL.md`
- Babysit: Cursor built-in `babysit/SKILL.md`
- Ship bar: repo `WORKFLOW.md`
- Rules: `~/.cursor/rules/git-pr-workflow-default.mdc`
