---
name: pr-watch-agent
description: >-
  One-shot open-PR cycle: bot/human thread closure, gates, squash merge,
  Pi deploy + verify on http://100.78.28.10/. Delegates path locks to chief.
---

# PR watch agent (AR-local)

Run one bounded ship-bar cycle on **yanniedog/AR-local** open pull requests: triage and close review threads, fix actionable failures, verify exact-head gates, and squash merge eligible PRs oldest first. When only GitHub work remains, park ownership and check once in a later turn. Pi deployment and acceptance follow separately authorized recovery gates.

You **combine** pr-fix (remediation), pr-gates (audit), workflow-orchestrator (merge + close-loop), pi-deploy-watchdog (runtime), and post-merge-verify (acceptance HTTP). You **do not** own unrelated feature implementation or path locks across concurrent agent branches — **chief** still assigns one writer per branch.

**Authoritative bar:** `WORKFLOW.md` steps **4–9** (+ **5b** synthesis, **8b** Pi when deploy paths change).

**Automation:** `npm run pr:queue:drive` or `npm run pr:watch-once`. See **`docs/HANDOFF.md` §6.1**.

## Invocation phrases

- **"run pr watch"** / **"watch open PRs"**
- Chief/orchestrator: *Follow `.cursor/skills/pr-watch-agent/SKILL.md` for one cycle, then record ownership and blockers.*
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

## One-shot cycle

### SCAN

```sh
git fetch origin
npm run pr:watch-once          # or --json for machine output
gh pr list --state open --json number,title,headRefName,createdAt,mergeable,mergeStateStatus
npm run chief:scan             # exit 1 → fix clashes before merging
```

**Merge order:** Process open PRs **oldest `createdAt` first** (script default). If multiple PRs touch `dashboard/app.css` or the same paths, **rebase the younger PR onto `origin/main`** after the older merges (dependency-aware). `pr:watch-once` prints `BEHIND` / `DIRTY` hints.

**Idle or waiting:** No open PRs → report **idle**. If only GitHub checks or merge processing remain, record the current head and blocker, park ownership, and check once in a later turn. Do not use watch or retry loops.

### Per PR (one evaluation per cycle)

#### 1. Orient

```sh
gh pr view <n> --json title,state,headRefName,statusCheckRollup
git fetch origin && git checkout <headRefName> && git rebase origin/main   # if behind
```

#### 2. Bot wait (step 5)

```sh
npm run wait-for-bots -- --pr <n>
```

Review vendors are advisory by default. Use `--require-bots gemini,codex,sourcery` only when explicitly requested. After @mentioning bots, `npm run wait-for-bots -- --bot-tag` resets the anchor; exit **2** parks ownership. Code-only pushes do **not** reset the anchor.

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
```

Merge **only** when `pr:gates:check` exit **0** (CI, GitHub `bot-*` gates, wait-for-bots, thread closure, feedback plan when required).

#### 5. Merge (step 7)

```sh
npm run pr:merge -- --pr <n> --no-sync
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
npm run pi:deploy:verify
# Record the exact drift and health evidence. Do not deploy the merge.
```

On SSH failure, report the unavailable verification. On drift, preserve the
current runtime until an immutable candidate has completed the canary matrix and
the protected exact-commit deployment gate is approved.

Optional: **post-merge-verify-agent** for evidence (Browser MCP on Pi URL).

## Resume ownership

| Mode | How |
|------|-----|
| Later turn | Re-invoke for one fresh cycle after parked GitHub work changes |
| Single check | `npm run pr:watch-once` |
| Chief assignment | One pr-watch worker at a time; retain ownership while parked |

```sh
npm run ship:closeout:strict && npm run wait-for-bots   # session idle only when no open PR work
```

## Return format

| Item | Value |
|------|--------|
| Open PRs scanned | # list oldest-first |
| Per-PR gates | pass / failing gate ids |
| Merges this cycle | PR # + SHA on main |
| Pi verification | verify exit / SHAs / drift retained |
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
