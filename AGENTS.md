# AR-local ? Agent configuration

Local CDR ingest, exports, and dashboard. Workflow matches **Australian Rates** for Git/PR/CI/bot/thread closure; **hosting and verification target the Pi dashboard** (no Cloudflare, no www.australianrates.com.au as the acceptance environment). **Do not default to `127.0.0.1`** — see **`.cursor/rules/pi-host-not-localhost.mdc`**.

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
- **Verification (Pi — primary):** **`npm run verify:local -- --base-url=http://100.78.28.10/`** or **`npm run verify:pi`** against the Pi dashboard (Tailscale; nginx :80). Override via **`AR_PI_BASE_URL`** or **`--base-url`**. Use **Browser MCP** against the same Pi URL. Local `127.0.0.1` only when the user explicitly runs the dev server locally.
- **Branding map:** **`dashboard/ar-bank-brand.js`** is loaded from **`/assets/`** so the dashboard works even when **`/site/ar-bank-brand.js`** is unavailable.

## Repo commands

| Purpose | Command |
|--------|---------|
| Bot wait gate (new PR) | `npm run wait-for-bots` |
| Bot thread closure gate | `npm run pr:bot-feedback-check -- --pr <n>` |
| PR merge gates (aggregate) | `npm run pr:gates:check -- --pr <n>` |
| PR watch one cycle | `npm run pr:watch-once` (oldest open PRs first; exit 2 = gates failing) |
| Merged PR bot audit | `npm run pr:bot-feedback-audit` |
| Closeout: open PR check | `npm run ship:closeout:strict` (includes bot-feedback gate) |
| Pi dashboard smoke HTTP (default acceptance) | `npm run verify:pi` or `npm run verify:local -- --base-url=http://100.78.28.10/` |
| Local dev smoke (explicit local server only) | `npm run verify:local -- --base-url=http://127.0.0.1:<port>/` |
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

**Targets (default):** **`http://100.78.28.10/`** (Pi Tailscale, nginx :80) per **`pi-host-not-localhost.mdc`** and **`docs/UNIVERSAL_ROADMAP.md`**. Local `127.0.0.1` only when the user explicitly requests local dev. SSH tunnel `127.0.0.1:18808` only when tunneling is required. Not production australianrates.com for acceptance unless comparing parity.

## Chief agent

Session **coordination authority** ? path locks, PR assignment, dedupe redundant spawns, supersede stale workers when the user changes direction. Sits **above** the workflow orchestrator.

| Piece | Location |
|-------|----------|
| Skill (locks, routing, handoff) | [`.cursor/skills/chief-agent/SKILL.md`](.cursor/skills/chief-agent/SKILL.md) |
| Always-on rule (manual invoke only) | [`.cursor/rules/chief-agent-always.mdc`](.cursor/rules/chief-agent-always.mdc) |

**Manual invoke:** say **"run chief agent"** — agent reads the skill and runs SCAN → LOCK CHECK → PLAN → DELEGATE. Chief is **not** auto-spawned on dirty tree, open PRs, or stop hooks.

**If chief reminders still inject:** Cursor also loads `%USERPROFILE%\.cursor\hooks.json`. Remove `orchestrator-remind.mjs` from `subagentStop`/`stop` there (repo `.cursor/hooks.json` is empty). Reload the window (Developer: Reload Window).

**Relationship to orchestrator:** chief owns coordination when invoked; orchestrator owns ship bar. Say **"run workflow orchestrator"** without chief, or chief may delegate. Orchestrator does not spawn chief.

## Continuous workflow orchestrator

Ship-bar guardian (reports to chief agent). Cursor subagents are **not** OS daemons.

| Piece | Location |
|-------|----------|
| Skill (scan, route, split PRs, loop) | [`.cursor/skills/workflow-orchestrator/SKILL.md`](.cursor/skills/workflow-orchestrator/SKILL.md) |
| Always-on rule (manual invoke) | [`.cursor/rules/workflow-orchestrator-always.mdc`](.cursor/rules/workflow-orchestrator-always.mdc) |
| Coordination hooks (opt-in, off) | `.cursor/hooks.json` (empty); `AR_LOCAL_COORDINATION_HOOKS=1` to re-enable |

**Manual invoke:** say **"run workflow orchestrator"** — agent reads the skill and runs SCAN → PLAN → DELEGATE.

**Policy:** one logical task → one branch → one PR. Chief prevents path conflicts when invoked; orchestrator executes split and ship bar.

## Team agents (specialized workers)

Chief assigns **one writer per path prefix and branch** when invoked. Each skill defines path locks, invoke phrases, and handoffs.

| Agent | Skill | Invoke | Relationship to chief |
|-------|-------|--------|------------------------|
| Pi deploy | [pi-deploy-agent/SKILL.md](.cursor/skills/pi-deploy-agent/SKILL.md) | **run pi deploy** | Post-merge runtime on Pi; SSH `/srv/ar-local`, pull `main`, restart units; smoke URL from `docs/UNIVERSAL_ROADMAP.md` |
| Pi deploy watchdog | [pi-deploy-watchdog/SKILL.md](.cursor/skills/pi-deploy-watchdog/SKILL.md) | **run pi deploy watchdog** | `npm run pi:deploy:verify` / scheduled Actions + Pi timer; auto-deploy via `npm run pi:deploy` |
| Ingest | [`.cursor/skills/ingest-agent/SKILL.md`](.cursor/skills/ingest-agent/SKILL.md) | **run ingest bring-up** | `cdr_daily.py` / `cdr_outputs.py` / `runs/`; real data only |
| Dashboard | [`.cursor/skills/dashboard-agent/SKILL.md`](.cursor/skills/dashboard-agent/SKILL.md) | **run dashboard agent** | `dashboard/**`, `cdr_dashboard_server.py`; one PR family per UI task |
| PR gates | [`.cursor/skills/pr-gates-agent/SKILL.md`](.cursor/skills/pr-gates-agent/SKILL.md) | **run pr gates agent** / **ensure PR gates** | Read-only: `npm run pr:gates:check`; hand off failures to pr-fix |
| PR fix | [`.cursor/skills/pr-fix-agent/SKILL.md`](.cursor/skills/pr-fix-agent/SKILL.md) | **run pr fix** | One PR: threads, CI, synthesis; orchestrator merges after gates pass |
| PR watch | [`.cursor/skills/pr-watch-agent/SKILL.md`](.cursor/skills/pr-watch-agent/SKILL.md) | **run pr watch** / **watch open PRs** | Continuous open-PR loop: gates, merge (oldest first), Pi deploy + verify; `npm run pr:watch-once`; chief holds path locks |
| Parity | [`.cursor/skills/parity-agent/SKILL.md`](.cursor/skills/parity-agent/SKILL.md) | **run parity check** | Prod vs local/Pi layout/CSS; not functional QA |
| Post-merge verify | [`.cursor/skills/post-merge-verify-agent/SKILL.md`](.cursor/skills/post-merge-verify-agent/SKILL.md) | **run post-merge verify** | `WORKFLOW.md` steps 8-9 after merge |
| Split PRs | [`.cursor/skills/split-pr-agent/SKILL.md`](.cursor/skills/split-pr-agent/SKILL.md) | **split PRs** | Partition mixed WIP; then orchestrator per slice |
| Site shell | [`.cursor/skills/site-shell-agent/SKILL.md`](.cursor/skills/site-shell-agent/SKILL.md) | **run site shell agent** | `australianrates/site/**`; separate from dashboard PRs |

**Also see:** chief, orchestrator, deep-browser-explore, agent-auditor (tables above).

## agentmemory is local — do NOT SSH to Pi for agentmemory

agentmemory (`@agentmemory/agentmemory`) is an npm package installed **globally on the Windows development machine**. Its engine, viewer, REST API, logs, config, and all data are local.

- **Never SSH into `ar-local-pi5` or any Pi host for agentmemory work.**
- Never treat the Pi as the agentmemory host or run agentmemory CLI commands over SSH.
- Config and data: `C:\Users\jkoka\.agentmemory\` — REST API: `http://localhost:3111` (local only).
- The Pi hosts only the CDR dashboard (`cdr_dashboard_server.py`) and ingest jobs.

Rule file: `.cursor/rules/agentmemory-is-local.mdc` (this workspace) and `C:\Users\jkoka\.cursor\rules\agentmemory-is-local.mdc` (global).

## Agent memory (agentmemory MCP)

All three agents (Cursor, Claude Code, Codex) share a local agentmemory server at `http://127.0.0.1:3111`. Context from previous sessions is **automatically injected** at session start via hooks — you do not need to request it manually.

**MCP tools available** (via `user-agentmemory` server in Cursor, `agentmemory` in Claude/Codex):

| Tool | When to use |
|------|-------------|
| `memory_recall` | Look up past decisions, file edits, or patterns by keyword |
| `memory_save` | Explicitly pin an important insight, architecture decision, or bug fix |
| `memory_lesson_save` | Record a reusable lesson (e.g. "always escape X before Y") |
| `memory_smart_search` | Semantic search across all stored observations |
| `memory_sessions` | Browse past sessions for this project |
| `memory_reflect` | Trigger consolidation of recent observations into long-term memory |
| `memory_consolidate` | Force a full consolidation cycle |
| `memory_diagnose` | Debug memory health or retrieval issues |

**Use proactively:**
- After a non-obvious fix or architectural decision → `memory_save`
- When starting work on a file you last touched in a prior session → `memory_recall`
- When context injection at session start is empty → prior sessions may not yet be consolidated; use `memory_smart_search` directly

**Config:** `%USERPROFILE%\.agentmemory\.env`, viewer at `http://127.0.0.1:3113`. Do not point agentmemory at the Pi — it is localhost-only.

## Debugging

- Use **fresh ingest/export outputs** and **dashboard server stdout/stderr**, not stale cached assumptions.
- If **`frequent_errors.txt`** exists in the repo root, check fixes against known recurring failures before claiming scripts are fine.
