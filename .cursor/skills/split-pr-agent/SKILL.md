---
name: split-pr-agent
description: >-
  Partition dirty tree into one PR per task; split-to-prs patterns. Chief invokes
  when WIP spans disjoint paths.
---

# Split PR agent (AR-local)

You turn **mixed WIP** (dirty tree, monolithic branch, or overloaded PR) into **one logical task → one branch → one PR** with disjoint path partitions. Chief invokes when scans show path clash or `chief:scan` REMEDIATION lists split needed.

**Patterns:** Cursor **`split-to-prs`** skill (`~/.cursor/skills-cursor/split-to-prs/SKILL.md`) — recoverable snapshots, staged files only, plan before execute.

**Reports to:** chief agent. After split, delegate **workflow-orchestrator** per PR for full ship bar.

## Environment URLs (do not hardcode)

If partitioned WIP mentions Pi deploy or parity URLs, reference **`docs/UNIVERSAL_ROADMAP.md`** — do not copy hardcoded Tailscale IPs into new skill or rule text.

## Invocation phrases

- **"split PRs"**
- Chief delegate: *Follow `.cursor/skills/split-pr-agent/SKILL.md`; partition paths: …*

## Path locks

| Owns | Rule |
|------|------|
| Git branch/stash operations for partitioning | Never `git add .` / `git add -A` |
| Proposing slice plan | No destructive git without user approval on this repo |
| Executing slices | Only after user/chief approves plan (AR-local user rule: commit when asked — chief approval counts for agent splits) |

## Hard rules (from split-to-prs)

- **Never discard user work.** No `reset --hard`, `clean -fdx`, branch delete, force-push without explicit approval.
- **Recoverable snapshot** before moving hunks:

```sh
SHA=$(git stash create "pre-split")
if [ -n "$SHA" ]; then
  git update-ref "refs/backup/pre-split-$(date +%s)" "$SHA"
fi
```

- Stage **named files or hunks only**.
- Default: independent PRs from `origin/main`; stack only when dependency is real.

## AR-local partition map (chief alignment)

| Path prefix | Typical owner agent | PR slug example |
|-------------|---------------------|-----------------|
| `cdr_daily.py`, `cdr_outputs.py`, `runs/`, `pi_daily_sync.py` | ingest-agent | `agent/ingest-*` |
| `dashboard/**`, `cdr_dashboard_server.py` | dashboard-agent | `agent/dashboard-*` |
| `deploy/pi/**`, Pi docs only | pi-deploy-agent | `agent/pi-deploy-*` |
| `docs/**` (non-feature) | generalPurpose / docs | `agent/docs-*` |
| `.cursor/skills/**`, rules, workflow scripts | workflow-orchestrator meta | `agent/workflow-*` |
| Sibling `australianrates/site/**` | site-shell-agent | separate repo PR often |

**Forbidden bundle:** ingest + dashboard + docs + orchestrator plumbing in one PR.

## Workflow

### 1. State check

```sh
git fetch origin
git status --porcelain
git diff --stat origin/main
gh pr list --state open
npm run chief:scan
```

Summarize slices from paths + chat intent. Note CODEOWNERS if present.

### 2. Propose plan (before branches)

For each slice:

- Branch name `agent/<topic>-<nonce>`
- File list (explicit)
- PR title + one-line scope
- Dependency order (if stacked)

Ask chief/user approval before creating branches when user has not pre-approved.

### 3. Execute per approved slice

```sh
git fetch origin && git checkout main && git pull origin main
git checkout -b agent/<slice-slug>
# stage only planned paths
git commit -m "..."
git push -u origin HEAD
gh pr create --base main --title "..." --body "..."
```

### 4. Report

- PR URLs per slice
- Leftover dirty paths on original branch
- Backup ref name
- Recommended next worker per PR (pr-fix, dashboard-agent, …)

## Chief handoff

After split, update branch lock registry — one writer per `agent/<slug>`. Spawn **workflow-orchestrator** or path owner per open PR.

## Anti-patterns

- Monolithic PR “for convenience”.
- Blind `stash pop` mixing partitions.
- Five parallel agents on same PR after split.

## Related

- `chief-agent` — remediation protocol, partition table
- `workflow-orchestrator` — ship bar per PR
- `split-to-prs` skill — generic mechanics
- `.cursor/rules/multiagent-modularity.mdc`
