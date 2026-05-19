# AR-local ? Agent configuration

Local CDR ingest, exports, and dashboard. Workflow matches **Australian Rates** for Git/PR/CI/bot/thread closure; **hosting and verification are local only** (no Cloudflare, no www.australianrates.com.au as the acceptance environment).

## Ship bar

Full procedure ? branch, commit, PR, CI, bot wait, feedback synthesis, thread closure, merge, **local dashboard**, **`npm run verify:local`** ? all steps required unless the user explicitly waives in writing for that PR.

**Read `WORKFLOW.md` in full** before opening or merging a PR.

Anti-early-stop:

```sh
npm run ship:closeout:strict && npm run wait-for-bots
```

- Exit **2** from `ship:closeout:strict` ? open PR still exists; continue `WORKFLOW.md` steps 5?9.
- Exit **2** from `wait-for-bots` ? bots/CI not settled; re-run until exit **0** (or use `--watch`).

Cursor rules live under **`.cursor/rules/`** (mirrors AustralianRates rule names and intent; Cloudflare and production-URL steps are replaced with local equivalents).

## Multiagent workflow and modular code

Same expectations as Australian Rates:

- Fresh **`origin/main`**, distinctive **`agent/<slug>`** (or feat/fix), no branch reuse across concurrent agents.
- Rebase/merge when stale; resolve overlaps with other topic branches deliberately.
- **`ci_result` (or equivalent) green ? merge-ready** ? complete wait gate, synthesis, and threaded replies per **`WORKFLOW.md`**.
- **Soft target ~800 LOC per file**, **hard ceiling ~1000 LOC**; split along natural seams when adding non-trivial code.
- **~50 lines per function** where practical; avoid copying the same logic in 3+ places.

Exemptions (do not refactor purely for size): `requirements.txt`, generated outputs under `runs/` (gitignored), lockfiles, `.env*`.

## Local site and dashboard

- **Dashboard:** `cdr_dashboard_server.py` serves **`dashboard/`** HTML/JS/CSS and proxies **`/site/*`** from the AustralianRates **`site`** directory when configured (auto-detect prefers a tree that has **`assets/banks/*.png`** when possible).
- **Canonical public shell assets** still come from the AustralianRates **`site`** folder on disk (clone **`australianrates`** beside this repo or pass **`--site-root`**). There is no Pages deploy from this repo.
- **Verification:** **`npm run verify:local`** against the running dashboard URL; use **Browser MCP** when validating UI.
- **Branding map:** **`dashboard/ar-bank-brand.js`** is loaded from **`/assets/`** so the dashboard works even when **`/site/ar-bank-brand.js`** is unavailable.

## Repo commands

| Purpose | Command |
|--------|---------|
| Bot wait gate (new PR) | `npm run wait-for-bots` |
| Bot thread closure gate | `npm run pr:bot-feedback-check -- --pr <n>` |
| PR merge gates (aggregate) | `npm run pr:gates:check -- --pr <n>` |
| Merged PR bot audit | `npm run pr:bot-feedback-audit` |
| Closeout: open PR check | `npm run ship:closeout:strict` (includes bot-feedback gate) |
| Local dashboard smoke HTTP | `npm run verify:local -- --base-url=http://127.0.0.1:<port>/` |
| Pi deploy verify / apply | `npm run pi:deploy:verify` / `npm run pi:deploy` |
| Pi deploy needed (post-merge gate) | `npm run pi:needs-deploy -- --ref origin/main~1` |
| Prune remote refs | `npm run git:graph-hygiene` |

Requires **Node** (for `npm run wait-for-bots`) and **Python** (for `verify:local` and ingest). Requires **`gh`** CLI for PR-driven steps.

## Project philosophy: real data only

Same stance as Australian Rates: **no mock or simulated business data** for acceptance. Dashboard and exports must use **generated artifacts** under **`runs/<date>/_exports/`** (or paths you pass to **`--exports`**). Do not fabricate rate rows or JSON for ?demo? behaviour.

## Presentation: data-first

Dense tables, compact controls, terse labels. Avoid marketing copy and narrative filler unless the user asks.

## Code quality

- Prefer focused changes; match existing style in Python and browser scripts.
- Keep **`cdr_dashboard_server.py`** routing explicit and safe (path traversal checks preserved).

## Deep browser exploration

Interactive UI QA via Browser MCP for navigation, hierarchy drill-down, screenshots, console/network capture. Complements **`verify:local`**; does not replace it for ship-bar sign-off.

| Piece | Location |
|-------|----------|
| Skill (MCP workflow, selectors, report format) | [`.cursor/skills/deep-browser-explore/SKILL.md`](.cursor/skills/deep-browser-explore/SKILL.md) |
| Manual-invoke rule (`dashboard/**` optional) | [`.cursor/rules/deep-browser-explore.mdc`](.cursor/rules/deep-browser-explore.mdc) |

**Invoke:** **deep browser explore**, **browser QA pass**, or **`/deep-browser-explore`**. Read MCP tool schemas under `user-browser_agent_cursor` each session.

**Targets:** `http://127.0.0.1:<port>/` (local) or Pi dashboard per **`docs/UNIVERSAL_ROADMAP.md`** (LAN/Tailscale IP, SSH tunnel). Not production australianrates.com for acceptance unless comparing parity.

## Chief agent

Session **coordination authority** ? path locks, PR assignment, dedupe redundant spawns, supersede stale workers when the user changes direction. Sits **above** the workflow orchestrator.

| Piece | Location |
|-------|----------|
| Skill (locks, routing, handoff) | [`.cursor/skills/chief-agent/SKILL.md`](.cursor/skills/chief-agent/SKILL.md) |
| Always-on rule (spawn chief first) | [`.cursor/rules/chief-agent-always.mdc`](.cursor/rules/chief-agent-always.mdc) |

**Manual invoke:** say **"run chief agent"** ? agent reads the skill and runs SCAN ? LOCK CHECK ? PLAN ? DELEGATE.

**Relationship to orchestrator:** chief owns multi-agent coordination; orchestrator owns ship bar (git/PR/CI/bot wait/merge/Pi). Parent agents spawn **chief first**; chief delegates git/PR work to orchestrator. Orchestrator does not spawn chief.

## Continuous workflow orchestrator

Ship-bar guardian (reports to chief agent). Cursor subagents are **not** OS daemons.

| Piece | Location |
|-------|----------|
| Skill (scan, route, split PRs, loop) | [`.cursor/skills/workflow-orchestrator/SKILL.md`](.cursor/skills/workflow-orchestrator/SKILL.md) |
| Always-on rule (chief delegates here) | [`.cursor/rules/workflow-orchestrator-always.mdc`](.cursor/rules/workflow-orchestrator-always.mdc) |
| Hook reminder (chief-first, then orchestrator) | [`.cursor/hooks/orchestrator-remind.mjs`](.cursor/hooks/orchestrator-remind.mjs) |

**Manual invoke:** say **"run workflow orchestrator"** ? usually via chief delegation; agent reads the skill and runs SCAN ? PLAN ? DELEGATE.

**Policy:** one logical task ? one branch ? one PR (no monolithic ingest + dashboard + docs bundles). Chief prevents path/PR conflicts; orchestrator executes split and ship bar.

## Team agents (specialized workers)

Chief assigns **one writer per path prefix and branch**. Each skill defines path locks, invoke phrases, and handoffs. Parent agents spawn **chief first**; chief delegates below.

| Agent | Skill | Invoke | Relationship to chief |
|-------|-------|--------|------------------------|
| Pi deploy | [pi-deploy-agent/SKILL.md](.cursor/skills/pi-deploy-agent/SKILL.md) | **run pi deploy** | Post-merge runtime on Pi; SSH `/srv/ar-local`, pull `main`, restart units; smoke URL from `docs/UNIVERSAL_ROADMAP.md` |
| Pi deploy watchdog | [pi-deploy-watchdog/SKILL.md](.cursor/skills/pi-deploy-watchdog/SKILL.md) | **run pi deploy watchdog** | `npm run pi:deploy:verify` / scheduled Actions + Pi timer; auto-deploy via `npm run pi:deploy` |
| Ingest | [`.cursor/skills/ingest-agent/SKILL.md`](.cursor/skills/ingest-agent/SKILL.md) | **run ingest bring-up** | `cdr_daily.py` / `cdr_outputs.py` / `runs/`; real data only |
| Dashboard | [`.cursor/skills/dashboard-agent/SKILL.md`](.cursor/skills/dashboard-agent/SKILL.md) | **run dashboard agent** | `dashboard/**`, `cdr_dashboard_server.py`; one PR family per UI task |
| PR gates | [`.cursor/skills/pr-gates-agent/SKILL.md`](.cursor/skills/pr-gates-agent/SKILL.md) | **run pr gates agent** / **ensure PR gates** | Read-only: `npm run pr:gates:check`; hand off failures to pr-fix |
| PR fix | [`.cursor/skills/pr-fix-agent/SKILL.md`](.cursor/skills/pr-fix-agent/SKILL.md) | **run pr fix** | One PR: threads, CI, synthesis; orchestrator merges after gates pass |
| Parity | [`.cursor/skills/parity-agent/SKILL.md`](.cursor/skills/parity-agent/SKILL.md) | **run parity check** | Prod vs local/Pi layout/CSS; not functional QA |
| Post-merge verify | [`.cursor/skills/post-merge-verify-agent/SKILL.md`](.cursor/skills/post-merge-verify-agent/SKILL.md) | **run post-merge verify** | `WORKFLOW.md` steps 8-9 after merge |
| Split PRs | [`.cursor/skills/split-pr-agent/SKILL.md`](.cursor/skills/split-pr-agent/SKILL.md) | **split PRs** | Partition mixed WIP; then orchestrator per slice |
| Site shell | [`.cursor/skills/site-shell-agent/SKILL.md`](.cursor/skills/site-shell-agent/SKILL.md) | **run site shell agent** | `australianrates/site/**`; separate from dashboard PRs |

**Also see:** chief, orchestrator, deep-browser-explore, agent-auditor (tables above).

## Debugging

- Use **fresh ingest/export outputs** and **dashboard server stdout/stderr**, not stale cached assumptions.
- If **`frequent_errors.txt`** exists in the repo root, check fixes against known recurring failures before claiming scripts are fine.
