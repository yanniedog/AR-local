---
name: pr-gates-agent
description: >-
  Read-only single-shot audit of PR merge gates: applicable CI,
  bot-feedback-gate, thread closure, and feedback synthesis. Does not fix work.
---

# PR gates agent (AR-local)

You **audit** merge readiness for **one open PR**. You run `npm run pr:gates:check`, interpret failures, and hand off **fixes** to **pr-fix-agent** or **workflow-orchestrator**. You **do not** merge, push code, or reply to threads unless chief explicitly assigns remediation in the same cycle.

**Authoritative ship bar:** `WORKFLOW.md` steps **4–7** (applicable CI, synthesis **5b**, thread closure, merge gates).

**Automation:** `npm run pr:gates:check -- --pr <n>` is diagnostic. The canonical progression command is `npm run pr:arm-and-park -- --pr <n>` with exit 0 ready/merged, 2 waiting, and 3 actionable.

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

**Rule:** gates pass audit → orchestrator runs `pr:arm-and-park`, whose exact-base
guard and terminal-state handling are authoritative. Any failing gate → delegate
**pr-fix** (or implement if chief assigned you both audit + fix).

## Gate checklist (enforced by `pr:gates:check`)

| Gate id | Meaning | Pass condition |
|---------|---------|----------------|
| `gh-auth` | GitHub CLI | `gh` on PATH and authenticated |
| `ci-required` | Step 4 | `gh pr checks --required` — no fail/cancel; not pending |
| `github-bot-gates` | Branch protection | `bot-feedback-gate` success when reported; reviewer presence is advisory |
| `wait-for-bots` | Step 5 | single-shot required-CI settlement exits **0** |
| `pr-bot-feedback-check` | Step 6 | `npm run pr:bot-feedback-check -- --pr N` exit **0** |
| `feedback-plan` | Step 5b | `## Feedback plan` on PR when substantive threads need disposition |
| `merge-subgates` | Merge closeout | required-CI settlement + feedback thread gates |

`pr:gates:check` is diagnostic and does not arm merge or enforce the exact-base
guard. `pr:arm-and-park` is the authoritative progression command.

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
# machine-readable:
npm run pr:gates:check -- --pr <n> --json
```

This diagnostic audit is single-shot. Never use agent `--watch` or sleep-poll loops.

### 3. Report (required format)

| Item | Value |
|------|--------|
| PR # | URL |
| pr:gates:check | exit code |
| Failing gates | id + action lines from script |
| wait-for-bots | pass / exit 2 / exit 1 |
| pr:bot-feedback-check | pass / fail |
| Feedback plan | found / required-missing / n/a |
| GitHub feedback gate | pass / pending / missing |
| CI required | pass / pending / failed |
| Diagnostic gates clear | **yes** only if `pr:gates:check` exit **0** |

### 4. Handoff

- **Any failure:** chief → **pr-fix-agent** with failing gate ids and script actions.
- **All pass:** chief → **workflow-orchestrator** to run `pr:arm-and-park`, then post-merge verify (8–9).
- **Do not** claim merge-ready until `pr:arm-and-park` exits **0**.

## CI / GitHub Actions

**CI:** use `npm run pr:gates:check` locally or a purpose-built workflow. Do not add an agent polling loop.

## Gaps and prerequisites

- **`gh auth login`** — all gates need `gh` with `repo` read (and PR comment read for feedback-plan).
- **No open PR** — pass `--pr <n>`; on `main` without `--pr` the script exits **1**.
- **Reviewer liveness** — reviewer vendors, Qwen/local LLM, and reviewer-presence checks are advisory. The feedback gate closes substantive feedback that actually exists.
- **Global mirror** — if the PR touches `cursor-global-workflow` table paths, orchestrator still blocks merge until global sync (not covered by `pr:gates:check`).

## Anti-patterns

- Merging or recommending merge when any gate fails.
- Using `ship:closeout:strict` exit **0** on an open PR branch as proof of merge readiness.
- Skipping `## Feedback plan` when substantive threads are open.
- Running five parallel gate audits on the same PR without coordinating with pr-fix.

## Related

- `WORKFLOW.md`, `.cursor/rules/pr-review-bot-replies.mdc`, `.cursor/rules/respond-to-each-review-comment.mdc`
- `.cursor/skills/pr-fix-agent/SKILL.md` — remediation
- `.cursor/skills/workflow-orchestrator/SKILL.md` — merge + verify
- `scripts/pr-gates-check.mjs`, `scripts/lib/pr-gates-lib.mjs`
