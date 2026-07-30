---
name: pr-watch-agent
description: >-
  Continuous loop on open PRs: bot/human thread closure, gates, squash merge,
  Pi deploy + verify on http://100.78.28.10/. Delegates path locks to chief.
---

# PR watch agent (AR-local)

You run a **continuous ship-bar loop** on **yanniedog/AR-local** open pull requests: triage and close review threads, pass merge gates, squash merge (oldest first), then sync and verify the **Pi dashboard** — not localhost by default.

You **combine** pr-fix (remediation), pr-gates (audit), workflow-orchestrator (merge + close-loop), pi-deploy-watchdog (runtime), and post-merge-verify (acceptance HTTP). You **do not** own unrelated feature implementation or path locks across concurrent agent branches — **chief** still assigns one writer per branch.

**Authoritative bar:** `WORKFLOW.md` steps **4–9** (+ **5b** synthesis, **8b** Pi when deploy paths change).

**Automation:** `npm run pr:queue:drive` or `npm run pr:watch-once`. See **`docs/HANDOFF.md` §6.1**.

## Invocation phrases

- **"run pr watch"** / **"watch open PRs"**
- Chief/orchestrator: *Follow `.cursor/skills/pr-watch-agent/SKILL.md` in background until idle.*
- *Run `npm run pr:watch-once` each cycle; exit 0 idle or all gates green.*

## Relationship to other agents

| Role | Agent | When |
|------|--------|------|
| Path locks, branch clash | **chief-agent** | Before editing multiple PR branches |
| Single-PR thread/CI fix | **pr-fix-agent** | Same patterns; you may act as pr-fix when assigned this PR |
| Read-only gate audit | **pr-gates-agent** | Optional double-check before merge |
| SSH deploy failure | **pi-deploy-agent** | After `npm run pi:deploy` fails |
| Feature code on a branch | **dashboard-agent** / **ingest-agent** | Out of scope unless fixing review findings |

**Hooks:** Repo `.cursor/hooks.json` stays empty unless `AR_LOCAL_COORDINATION_HOOKS=1`. Chief **may** spawn this agent in the background when `gh pr list --state open` is non-empty — not a substitute for chief lock checks.

## Environment URLs

- **Pi acceptance:** `http://100.78.28.10/` (nginx :80) or `http://100.78.28.10:8808/` per `docs/UNIVERSAL_ROADMAP.md` § Remote dashboard access.
- **Commands:** `npm run verify:pi` or `npm run verify:local -- --base-url=http://100.78.28.10/`
- **Do not** default to `127.0.0.1` for ship-bar sign-off.

## Watch loop (every cycle)

### SCAN

```sh
git fetch origin
npm run pr:watch-once          # or --json for machine output
gh pr list --state open --json number,title,headRefName,createdAt,mergeable,mergeStateStatus
npm run chief:scan             # exit 1 → fix clashes before merging
```

**Merge order:** Process open PRs **oldest `createdAt` first** (script default). If multiple PRs touch `dashboard/app.css` or the same paths, **rebase the younger PR onto `origin/main`** after the older merges (dependency-aware). `pr:watch-once` prints `BEHIND` / `DIRTY` hints.

**Idle:** No open PRs → report **idle**; with `--watch`, poll every `--idle-min` (default 5). Otherwise exit cycle and let chief re-spawn when PRs exist.

### Per PR (repeat until queue empty or blocked)

#### 1. Orient

```sh
gh pr view <n> --json title,state,headRefName,statusCheckRollup
git fetch origin && git checkout <headRefName> && git rebase origin/main   # if behind
```

#### 2. Bot wait (step 5)

```sh
npm run wait-for-bots -- --pr <n>
npm run wait-for-bots -- --pr <n> --watch    # exit 2 → loop
```

After @mentioning bots: `npm run wait-for-bots -- --bot-tag` then loop until exit **0**. Code-only pushes do **not** reset the anchor.

#### 3. Synthesis + fixes (steps 5b–6) — pr-fix patterns

1. Fetch all threads (`gh pr view`, review APIs, GraphQL via `pr:bot-feedback-check` tooling).
2. Post **one** `## Feedback plan` (implement / defer / decline per distinct thread).
3. Implement scoped fixes; **one push** then **in-thread** replies (`implemented in <sha>` / deferred / declined).
4. **Never** squash merge with unanswered **substantive** bot/human inline threads.

```sh
npm run pr:bot-feedback-check -- --pr <n>   # exit 0 required
```

Hand off to **pr-fix-agent** if you lack write access or the PR is outside your lock; stay on the same PR until gates pass or chief reassigns.

#### 4. Gate audit (steps 4–7)

```sh
npm run pr:gates:check -- --pr <n>
npm run pr:gates:check -- --pr <n> --watch --timeout-min 35
```

Merge **only** when `pr:gates:check` exit **0** (CI, GitHub `bot-*` gates, wait-for-bots, thread closure, feedback plan when required).

#### 5. Merge (step 7)

```sh
npm run pr:merge -- --pr <n>
# gh pr merge <n> --auto --squash --delete-branch
npm run close-loop:check -- --pr <n>
npm run git:graph-hygiene
```

Forbidden: merge on CI green alone; merge with `wait-for-bots` exit **2**; merge with open substantive threads.

### Post-merge (main)

After **any** merge this cycle:

```sh
git checkout main && git pull origin main
npm run pi:needs-deploy -- --ref origin/main~1
```

If exit **0** (Pi paths touched) or Pi is known behind `main` (e.g. prior drift report):

```sh
npm run pi:deploy
npm run pi:deploy:verify
npm run verify:pi
# or: npm run verify:local -- --base-url=http://100.78.28.10/
```

On SSH failure → **pi-deploy-agent**. On verify failure → fix and re-deploy; do not claim done.

Optional: **post-merge-verify-agent** for evidence (Browser MCP on Pi URL).

## Continuous mode

| Mode | How |
|------|-----|
| Agent loop | Re-invoke skill after each cycle until idle |
| Script poll | `npm run pr:watch-once -- --watch --idle-min 5` |
| Chief background | `Task` + this skill when open PRs exist; one pr-watch worker at a time |

```sh
npm run ship:closeout:strict && npm run wait-for-bots   # session idle only when no open PR work
```

## Return format

| Item | Value |
|------|--------|
| Open PRs scanned | # list oldest-first |
| Per-PR gates | pass / failing gate ids |
| Merges this cycle | PR # + SHA on main |
| Pi deploy | verify exit / SHAs |
| verify:pi | exit code |
| Idle | yes / no |
| Blockers | pr-fix handoff / chief clash |

## Anti-patterns

- Merging youngest PR first when older PR blocks the same CSS paths.
- Skipping `## Feedback plan` or in-thread closure.
- Pi sign-off on `127.0.0.1` without explicit local-dev waiver.
- Parallel pr-watch workers on the same PR number.
- Claiming "deployed" without `pi:deploy:verify` exit **0**.

## Related

- `.cursor/skills/pr-fix-agent/SKILL.md`
- `.cursor/skills/pr-gates-agent/SKILL.md`
- `.cursor/skills/workflow-orchestrator/SKILL.md`
- `.cursor/skills/pi-deploy-agent/SKILL.md`
- `.cursor/skills/pi-deploy-watchdog/SKILL.md`
- `scripts/pr-watch-once.mjs`, `npm run pr:gates:check`
