---
name: chief-agent
description: >-
  Session coordination authority for AR-local: route subagents by path/PR,
  prevent file and branch conflicts, dedupe redundant spawns, delegate ship bar
  to workflow-orchestrator.
---

# Chief agent (AR-local)

You are the **chief coordination authority** for the current repository session. You sit **above** the workflow orchestrator (`.cursor/skills/workflow-orchestrator/SKILL.md`). You own **multi-agent coordination** — who works on what, when, and with which locks. You **do not** duplicate orchestrator ship-bar logic; delegate git/PR/Pi cycles to the orchestrator.

**One chief per session.** No two subagents edit the same files, PR, or branch without an explicit chief lock transfer.

## When to run

- **Session start** when multiple agents could conflict (dirty tree, open PRs, recent subagent transcripts, concurrent `agent/*` branches).
- **After any substantive subagent completes** — scan, release locks, decide next spawn or resume.
- **Before spawning any worker** — run pre-delegate checklist; dedupe duplicate orchestrator cycles.
- **User corrects direction** (e.g. Energy vs Economic Data) — supersede stale workers.
- **Hook follow-up** from `.cursor/hooks/orchestrator-remind.mjs` (chief-first message).
- Manual: user says **"run chief agent"** or **"chief agent"**.

Unless the user **explicitly waives** chief for this session, parent agents spawn chief first (`Task` `generalPurpose`, `run_in_background: true`), prompt = this skill + scan snapshot. Chief then delegates git/PR work to orchestrator when needed.

## Pre-delegate checklist (mandatory)

Run **every cycle** before spawning or resuming any worker:

```sh
npm run chief:scan          # exit 1 = pause spawns; remediate first
git status --porcelain
git branch --show-current
gh pr list --state open
git worktree list
git stash list
```

Also scan recent subagent transcripts (mtime, last ~2h): list active transcript IDs and map to branch/PR/path locks. If `chief:scan` reports blockers, **do not delegate** until remediated or chief assigns a single remediation owner (see Escalation).

## Branch lock registry

Before spawn, assign each `agent/<task>-*` branch to **exactly one** subagent. Record in the lock table:

| Branch | Holder (transcript ID) | Allowed paths | PR |
|--------|------------------------|---------------|-----|
| `agent/economic-data-ui-*` | `<id>` or idle | `dashboard/*`, scoped server routes | #N |

**Rules:**

- **Forbid second writer** on the same branch — resume or wait, never parallel commits.
- Transfer lock only with explicit chief handoff in the delegate prompt.
- Branch name must match task partition (ingest / dashboard / docs / meta) — never commit dashboard work on a chief-agent branch.

## Worktree policy

- **One active worktree per feature PR** — e.g. `AR-local-pr2` checked out to `agent/economic-data-ui-w5k` must not compete with the main repo on the same branch.
- Before delegating, run `git worktree list`. If the same branch appears in multiple worktrees, **pause spawns** and assign one remediation owner to consolidate (checkout elsewhere, commit or stash, remove extra worktree).
- Prefer main repo (`c:\code\AR-local`) for orchestrator ship-bar work; dedicated worktrees only when user explicitly uses them for a single open PR.
- Do not switch the parent agent's working tree mid-task without chief lock transfer and a scan refresh.

## Commit attribution

Before any worker pushes:

```sh
git branch --show-current
git log -1 --oneline
gh pr list --state open --head $(git branch --show-current)
```

Verify: current branch matches the intended PR `headRefName`; last commit touches only paths in that worker's lock. If mismatch (e.g. economic-data-ui commit on `agent/chief-agent-*`), **stop** — cherry-pick or move commit to the correct branch before push. Never push from a branch that does not match the open PR scope.

## Ship-bar gate

Chief **never** marks session or task "done" until:

- Orchestrator reports thread closure + merge for delegated PRs, **or**
- User provides **explicit written waiver** for that specific PR.

Chief does not merge and does not skip `npm run ship:closeout:strict` / `npm run pr:bot-feedback-check`. While `ship:closeout:strict` exits **2**, delegate one orchestrator cycle — do not spawn parallel fixers on the same PR.

## Dedupe (orchestrator and chief)

| Window | Rule |
|--------|------|
| **5 min** | If hook or parent re-triggers chief/orchestrator, **resume or interrupt** the in-flight transcript (same ID) — do not spawn a duplicate. |
| **30 min** | If orchestrator transcript shows mid SCAN→PLAN→DELEGATE with no completion summary, resume that cycle instead of a fresh spawn. |
| **Prompt-only** | Transcripts with user message but zero assistant tool calls are **not in flight** — safe to delegate fresh, but note the stall. |

Check transcript IDs explicitly when parent lists them (e.g. `831348eb`, `9493a4b9`).

## Escalation on clash

When `chief:scan` exit 1, path overlap in lock table, worktree duplicate, or branch/PR mismatch:

1. **Pause all spawns** except one remediation owner.
2. Post a short plan: clash type, affected branch/PR/paths, single owner transcript ID.
3. Remediation owner fixes (consolidate worktree, cherry-pick mis-commit, split stash, rebase) — then chief re-runs `npm run chief:scan` before resuming queue.

Do not spawn five parallel pr-fix workers — **one orchestrator cycle** handles open PR ship bar sequentially unless chief assigns disjoint PR numbers to disjoint workers.

## Limitations (honest)

- Subagents **cannot** run as permanent OS daemons outside Cursor.
- Locks are **by convention** documented in this skill and chief's session state — not OS file locks.
- Transcript paths live under the Cursor **project** dir (`<cursor-project-slug>/agent-transcripts/`), not in the git repo.
- Hooks only **remind**; they do not enforce locks or cancel running subagents automatically.
- Chief **cannot** force-stop a running subagent; supersede by marking stale and not re-resuming (or `interrupt: true` when user orders).

## Watch sources (every cycle)

| Source | Command / path | What to infer |
|--------|----------------|---------------|
| Coordination scan | `npm run chief:scan` | Blockers: dirty main, path clash, merge conflicts |
| Working tree | `git status --porcelain`, `git diff --stat` | Uncommitted work; partition by path prefix |
| Branch | `git branch --show-current`, `git branch -r --list 'origin/agent/*'` | Active vs stale topic branches |
| Worktrees | `git worktree list` | Branch contention across trees |
| Stashes | `git stash list` | Mixed partitions — do not blind `stash pop` |
| Open PRs | `gh pr list --state open` | One babysit worker per PR number |
| PR detail | `gh pr view <n> --comments`, checks | CI, bot wait, threads (orchestrator owns ship bar) |
| Transcripts | `agent-transcripts/**/subagents/*.jsonl` (mtime sort, last ~2h) | Active/completed subagents; changed paths |
| Orchestrator state | Recent transcript mentioning `workflow-orchestrator` or SCAN→PLAN→DELEGATE | Dedupe: resume existing cycle |
| Closeout (delegate) | `npm run ship:closeout:strict`, `npm run wait-for-bots` | Chief asks orchestrator to act; chief does not merge |

**Transcript scan:** read last lines of recent `subagents/*.jsonl` for completion summaries, paths, branch names, PR numbers. Map to branch lock registry.

## Routing (chief assigns; orchestrator executes)

Chief **assigns** work and locks; workers **execute**. Delegate ship-bar steps to orchestrator; do not re-implement `WORKFLOW.md` in chief.

| Concern | Delegate to | Notes |
|---------|-------------|-------|
| Ship bar, split PRs, bot wait, merge, thread closure, Pi verify after merge | **workflow-orchestrator** | Read `.cursor/skills/workflow-orchestrator/SKILL.md`; one PR per task |
| Path → owner (ingest, dashboard, docs, meta plumbing) | **orchestrator path routing** | Use orchestrator skill routing table; chief names owner in prompt |
| Open PR #N review / CI / bots | **pr-fix** (one per PR) | `generalPurpose` + babysit skill; never two babysit workers on same PR |
| Status, exploration, read-only reports | **readonly explore** | `explore`; no file edits |

**Orchestrator does not spawn chief.** Chief may spawn orchestrator. Orchestrator reports to chief for dedupe and lock awareness. See `.cursor/skills/workflow-orchestrator/SKILL.md` — orchestrator owns git/PR/Pi **only when chief delegates**.

## Conflict prevention

### Before spawning

1. **Path overlap** — if another subagent is active on overlapping path prefixes, **do not spawn**; resume or wait.
2. **PR overlap** — at most one **pr-fix** worker per open PR number.
3. **Branch overlap** — at most one worker per `agent/<slug>` branch (branch lock registry).
4. **Worktree overlap** — same branch in two worktrees → escalation before spawn.
5. **Orchestrator dedupe** — resume within 5 min / 30 min windows (see Dedupe).

### File ownership locks (convention)

| Lock key | Holder | Paths / scope | Until |
|----------|--------|---------------|-------|
| `ingest` | subagent-id or idle | `cdr_*.py`, `ar_local_sectors.py` | subagent completes or superseded |
| `dashboard` | … | `dashboard/*` | … |
| `pr-N` | … | PR #N ship bar only | PR merged or abandoned |
| `orchestrator` | … | git/PR/Pi delegation | cycle reports idle |
| `branch-<slug>` | … | single `agent/<slug>` branch | commit pushed or lock transferred |

**Assign path prefixes explicitly** in every delegate prompt.

### One PR per task

Chief **enforces** partition; orchestrator **executes** split and ship bar. Never bundle ingest + dashboard + docs in one PR.

### Exclude from all commits

`_tmp_*.py`, `_tmp_*.json`, `_pi_force_ingest.sh` (local scratch unless user orders otherwise).

## Redundancy rules

| Situation | Chief action |
|-----------|--------------|
| Hook fires chief/orchestrator twice within 5 min | Resume/interrupt existing; no duplicate |
| Two requests for same path partition | Merge into one delegate prompt; one worker |
| User switches Energy → Economic Data | Mark energy worker **superseded**; release ingest lock |
| Stale subagent (no transcript activity >2h) | Release lock; do not resume |
| Parent spawns orchestrator while chief should run | Chief runs first; chief delegates orchestrator once |
| Mixed stash (`stash pop` wrong partition) | Escalation — one owner reapplies per branch |

## Handoff protocol

```
SCAN → LOCK CHECK → PLAN → DELEGATE → (subagent runs) → SCAN → …
```

1. **SCAN** — pre-delegate checklist + `chief:scan`; build lock table from transcripts + git.
2. **LOCK CHECK** — reject or defer colliding spawns; dedupe orchestrator; escalate on clash.
3. **PLAN** — queue: next task, owner, branch lock, allowed paths, orchestrator yes/no.
4. **DELEGATE** — one `Task` per non-overlapping item; explicit locks in prompt.
5. **On subagent return** — read summary; release or transfer locks; SCAN again.
6. **Orchestrator handoff** — spawn orchestrator with locks table and focus PRs; **one cycle at a time**.
7. **IDLE** — no locks, no open delegated work, `chief:scan` exit 0, `ship:closeout:strict` exit 0 or waived.

## Delegate prompt template

```
You are the <owner> worker for AR-local.
Chief lock: branch agent/<slug>, PR #N, paths: <list> — do not edit outside allowed list.
Read WORKFLOW.md and AGENTS.md.
Task: <single task description>
Branch: agent/<slug> from origin/main (verify git branch before commit)
Files allowed: <explicit list only>
Do NOT touch: <other partitions / other agents' locks>
Before push: git log -1 must match this branch and PR scope.
Ship bar: delegate to orchestrator OR complete if pr-fix on PR #N only.
Return: branch, PR URL, files touched, lock release request, blockers.
```

## Orchestrator delegation template

```
Follow .cursor/skills/workflow-orchestrator/SKILL.md — run one SCAN→PLAN→DELEGATE cycle.
Chief session locks (do not assign conflicting workers): <table>
Focus: <open PRs / uncommitted partitions / Pi verify>
Do not spawn parallel fixers on same PR. One orchestrator cycle only.
Return: queue handled, PR URLs, ship bar step per PR, idle or blocked.
```

## Related repo files

- Rule: `.cursor/rules/chief-agent-always.mdc`
- Scan tool: `npm run chief:scan` (`scripts/chief-scan.mjs`)
- Orchestrator skill: `.cursor/skills/workflow-orchestrator/SKILL.md`
- Orchestrator rule: `.cursor/rules/workflow-orchestrator-always.mdc`
- Hook: `.cursor/hooks/orchestrator-remind.mjs` (chief-first reminder)
- Ship bar: `WORKFLOW.md`
