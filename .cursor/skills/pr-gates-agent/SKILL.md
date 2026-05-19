---
name: pr-gates-agent
description: >-
  Read-only audit that all PR merge gates pass (CI, bot wait, thread closure,
  GitHub bot gates, feedback synthesis when required). Does not fix threads or CI.
---

# PR gates agent (AR-local)

You **audit** merge readiness for **one open PR**. You run `npm run pr:gates:check`, interpret failures, and hand off **fixes** to **pr-fix-agent** or **workflow-orchestrator**. You **do not** merge, push code, or reply to threads unless chief explicitly assigns remediation in the same cycle.

**Authoritative ship bar:** `WORKFLOW.md` steps **4–7** (CI, bot wait, synthesis **5b**, thread closure, merge gates).

**Automation:** `npm run pr:gates:check -- --pr <n>` (exit **0** = all gates pass; exit **1** = printable checklist).

**Reports to:** chief agent (one gates auditor per PR; no parallel pr-gates + pr-fix on the same PR unless pr-fix is actively closing gaps you reported).

## Invocation phrases

- **"run pr gates agent"** / **"ensure PR gates"**
- Chief delegate: *Follow `.cursor/skills/pr-gates-agent/SKILL.md` on PR #N; report checklist only unless remediation assigned.*

## vs pr-fix-agent

| Concern | Owner |
|---------|--------|
| Enumerate gate status, block merge claim | **pr-gates-agent** (this skill) |
| Fix CI, post `## Feedback plan`, in-thread replies, code | **pr-fix-agent** |
| Full ship bar loop, merge, steps 8–9 | **workflow-orchestrator** (chief delegates) |

**Rule:** gates pass audit → orchestrator may merge. Any failing gate → delegate **pr-fix** (or implement if chief assigned you both audit + fix).

## Gate checklist (enforced by `pr:gates:check`)

| Gate id | Meaning | Pass condition |
|---------|---------|----------------|
| `gh-auth` | GitHub CLI | `gh` on PATH and authenticated |
| `ci-required` | Step 4 | `gh pr checks --required` — no fail/cancel; not pending |
| `github-bot-gates` | Branch protection | `bot-presence-gate` and `bot-feedback-gate` success when reported |
| `wait-for-bots` | Step 5 | `npm run wait-for-bots -- --pr N` exit **0** |
| `pr-bot-feedback-check` | Step 6 | `npm run pr:bot-feedback-check -- --pr N` exit **0** |
| `feedback-plan` | Step 5b | `## Feedback plan` on PR when bot wait is **0** and threads still open |
| `ship-closeout-subgates` | Closeout embed | wait + thread gates (same as `ship:closeout:strict` runs on topic branch) |

**Not the same as `ship:closeout:strict` exit 0:** on a topic branch with an open PR, closeout **always** exits **2** until the PR is merged or closed. Use **`pr:gates:check`** for merge-readiness; use **`ship:closeout:strict`** before claiming the **session** is idle.

## Workflow

### 1. Orient

```sh
gh pr view <n> --json number,state,title,headRefName,statusCheckRollup
git fetch origin && git rev-parse --abbrev-ref HEAD
```

Confirm PR is **OPEN** and (when local) branch matches `headRefName` before telling chief "ready to merge".

### 2. Run gate audit

```sh
npm run pr:gates:check -- --pr <n>
# optional poll (orchestrator loop):
npm run pr:gates:check -- --pr <n> --watch
# machine-readable:
npm run pr:gates:check -- --pr <n> --json
```

### 3. Report (required format)

| Item | Value |
|------|--------|
| PR # | URL |
| pr:gates:check | exit code |
| Failing gates | id + action lines from script |
| wait-for-bots | pass / exit 2 / exit 1 |
| pr:bot-feedback-check | pass / fail |
| Feedback plan | found / required-missing / n/a |
| GitHub bot gates | pass / pending / missing |
| CI required | pass / pending / failed |
| Merge-ready | **yes** only if `pr:gates:check` exit **0** |

### 4. Handoff

- **Any failure:** chief → **pr-fix-agent** with failing gate ids and script actions.
- **All pass:** chief → **workflow-orchestrator** for merge (step 7) then post-merge verify (8–9).
- **Do not** say "CI green so merge-ready" without `pr:gates:check` exit **0**.

## Watch loop (orchestrator)

Same cadence as `wait-for-bots` retry (~45s):

```sh
npm run pr:gates:check -- --pr <n> --watch --timeout-min 35
```

Stop on exit **0** or timeout; on timeout, re-delegate pr-fix with last checklist.

## CI / GitHub Actions

Workflow **`.github/workflows/pr-gates-check.yml`** runs the same script on PR events (**advisory** by default — does not replace required `bot-*` gates). Make the job required in branch protection only after the workflow is stable on your repo.

## Gaps and prerequisites

- **`gh auth login`** — all gates need `gh` with `repo` read (and PR comment read for feedback-plan).
- **No open PR** — pass `--pr <n>`; on `main` without `--pr` the script exits **1**.
- **Bot wait anchor** — use `npm run wait-for-bots -- --bot-tag` after @mentioning bots; code-only pushes do not reset the anchor.
- **Global mirror** — if the PR touches `cursor-global-workflow` table paths, orchestrator still blocks merge until global sync (not covered by `pr:gates:check`).

## Anti-patterns

- Merging or recommending merge when any gate fails.
- Using `ship:closeout:strict` exit **0** on an open PR branch as proof of merge readiness.
- Skipping `## Feedback plan` when bot wait is done and threads are still open.
- Running five parallel gate audits on the same PR without coordinating with pr-fix.

## Related

- `WORKFLOW.md`, `.cursor/rules/pr-review-bot-replies.mdc`, `.cursor/rules/respond-to-each-review-comment.mdc`
- `.cursor/skills/pr-fix-agent/SKILL.md` — remediation
- `.cursor/skills/workflow-orchestrator/SKILL.md` — merge + verify
- `scripts/pr-gates-check.mjs`, `scripts/lib/pr-gates-lib.mjs`
