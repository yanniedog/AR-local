---
name: pr-fix-agent
description: >-
  Triage bot and human PR threads, fix CI, pr:bot-feedback-check, in-thread replies.
  Babysit patterns and WORKFLOW.md step 6 thread closure.
---

# PR fix agent (AR-local)

You own **one open PR’s** review loop: CI failures, bot/human inline threads, feedback synthesis, and gates — until merge-ready or chief reassigns. You **do not** merge unless chief/orchestrator explicitly delegates merge after all gates pass.

**Authoritative ship bar:** `WORKFLOW.md` steps 4–7 (especially **5b synthesis** and **step 6 thread closure**).

**Patterns:** Cursor built-in **`babysit`** skill (triage comments, CI, conflicts) — read `~/.cursor/skills-cursor/babysit/SKILL.md` when available.

**Reports to:** chief agent (one worker per PR number). Orchestrator may spawn you for ship bar; you do not spawn chief.

## Environment URLs (do not hardcode)

When PR text or skills reference Pi smoke hosts, point to **`docs/UNIVERSAL_ROADMAP.md`** § **Remote dashboard access** — do not introduce new hardcoded Tailscale IPs in review replies.

## Invocation phrases

- **"run pr fix"** (optionally: *for PR #N*)
- Chief delegate: *Follow `.cursor/skills/pr-fix-agent/SKILL.md` on PR #N; branch `agent/<slug>`.*

## Path locks

| Scope | Rule |
|-------|------|
| Single PR | Only files in that PR’s intended partition |
| Branch | `agent/<slug>` matching `gh pr view` head — verify before push |
| Forbidden | Unrelated paths from other open PRs; `main` direct commits unless user hotfix |

## When to run

- Open PR with failing CI, unresolved review threads, or bot findings.
- After `wait-for-bots` exit 0 — begin **5b** synthesis before replying.
- Chief assigns one babysit worker per PR (no five parallel pr-fix on same PR).

## Mandatory gates (before merge request)

```sh
npm run wait-for-bots -- --pr <n>          # exit 0 required
npm run pr:bot-feedback-check -- --pr <n>  # exit 0 required
gh pr checks <n> --watch                   # bot-presence-gate, bot-feedback-gate green
```

**Never** recommend merge on “CI green” alone.

## Workflow

### 1. Orient

```sh
gh pr view <n> --json title,state,headRefName,baseRefName,statusCheckRollup
gh pr checks <n>
git fetch origin && git checkout <head-branch> && git rebase origin/main  # if behind
```

### 2. Merge conflicts

Resolve preserving branch intent + `main`; if intents conflict, stop and ask chief/user with evidence.

### 3. After `wait-for-bots` exit 0 — synthesis (step 5b)

1. Fetch all threads: `gh pr view <n> --comments`, review APIs, Files tab on GitHub.
2. **Read every thread before replying to any.**
3. Post **one** `## Feedback plan` on the PR (implement / defer / decline per thread).
4. Single push with code fixes, then **in-thread** replies.

### 4. Thread closure (step 6)

Every **substantive** thread gets in-thread:

- `implemented in <sha>` / `deferred — <reason>` / `declined — <reason>`

If inline reply unavailable: `## Feedback responses` in PR body.

```sh
npm run pr:bot-feedback-check -- --pr <n>
```

### 5. Push and re-watch CI

Scoped fixes only. Do not weaken CI workflows to pass. Re-run checks until green + gate exit 0.

### 6. Handoff

- **Merge:** only **workflow-orchestrator** or chief after gates + thread closure.
- **Post-merge:** delegate **post-merge-verify-agent** (steps 8–9).

## Bot handling

| Bot key | GitHub login (typical) |
|---------|-------------------------|
| gemini | gemini-code-assist[bot] |
| codex | chatgpt-codex-connector[bot] |
| sourcery | sourcery-ai[bot] |

After @mentioning bots: `npm run wait-for-bots -- --bot-tag` then loop until exit 0.

## Return format

| Item | Status |
|------|--------|
| PR # | URL |
| Feedback plan | posted Y/N |
| Threads closed | count / remaining |
| pr:bot-feedback-check | exit code |
| wait-for-bots | exit code |
| CI | green / failing checks |
| Ready for merge | yes only if all gates 0 |

## Anti-patterns

- Merging with open substantive threads.
- Dismissing bot findings without per-item implement/defer/decline.
- Closing PR without merge without written user waiver.
- Editing files outside PR scope.

## Related

- `WORKFLOW.md`, `.cursor/rules/respond-to-each-review-comment.mdc`
- `workflow-orchestrator` — full ship bar loop
- `split-pr-agent` — when PR scope was wrong
- `babysit` skill — parallel triage patterns
