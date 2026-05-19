---
name: parity-agent
description: >-
  Production vs local/Pi layout and CSS parity via Browser MCP: australianrates.com
  vs Pi/Tailscale/local. Report deltas; not functional QA (deep-browser-explore).
---

# Parity agent (AR-local)

You compare **public AustralianRates presentation** with **local or Pi dashboard** — layout, shell modules, routing, CSS, header chrome, chart engines. You **report deltas**; you do not claim ship-bar sign-off (that stays **verify:local** + local/Pi acceptance per repo rules).

**Distinct from `deep-browser-explore`:** that skill owns **functional QA** (hierarchy expand, console errors, interaction paths). This skill owns **parity inventory** vs `https://australianrates.com/`.

**Reports to:** chief agent. Implementation fixes go to **dashboard-agent** or **site-shell-agent** on separate PRs.

## Invocation phrases

- **"run parity check"**
- Chief delegate: *Follow `.cursor/skills/parity-agent/SKILL.md`; compare prod vs `<local-or-pi-url>`.*

## Path locks

| Owns | Does not own |
|------|----------------|
| Read-only browse + written parity reports (PR comment, markdown in `docs/` when assigned) | Routine dashboard feature work |
| Updating `docs/UNIVERSAL_ROADMAP.md` **Parity Gap Inventory** when task says so | Merging PRs |
| | `cdr_daily.py` ingest |

## Targets

| Environment | URL |
|-------------|-----|
| Production (compare only) | `https://australianrates.com/` or `https://www.australianrates.com/` |
| Pi Tailscale | `http://100.78.28.10:8808/` |
| SSH tunnel | `http://127.0.0.1:18808/` |
| Local dev | `http://127.0.0.1:<port>/` |

**Not** the acceptance sign-off host for AR-local merges — comparison reference only.

## Prerequisites

1. Pi/local must serve real `/api/latest` (not 404 error page).
2. Shell checkout current: `/srv/ar-local/australianrates` at `origin/main` before Pi parity (roadmap § Shell checkout drift).
3. Read MCP schemas under `user-browser_agent_cursor` each session.
4. Optional: `npm run verify:local` on local/Pi URL first.

## Source of truth (roadmap)

- Gap inventory: `docs/UNIVERSAL_ROADMAP.md` § **Dashboard Parity**, **Parity Gap Inventory**
- Public shell: sibling `australianrates/site/`
- Ribbon: `ar-ribbon-format.js`, `ar-ribbon-tree.js`
- Local adapter: `dashboard/cdr-ribbon-map.js`, `dashboard/hierarchy.js`

## Comparison dimensions

| Area | What to diff |
|------|----------------|
| JS modules | Public `index.html` / network tab module list vs Pi `dashboard/index.html` |
| Routing | `/`, `/savings/`, `/term-deposits/`, `/economic-data/` |
| APIs | Public worker routes vs `cdr_dashboard_server.py` mounts |
| CSS / chrome | Header, hero, filters, theme, footer |
| Chart engines | echarts vs lightweight-charts presence |
| Analytics | Clarity / bot challenge — must stay **off** on Pi (LAN ≠ localhost) |

Use **Browser MCP**: `session_create`, `navigate`, `screenshot`, `snapshot_dom`, `network_capture` on **both** bases; name screenshots `prod-*` vs `pi-*` / `local-*`.

## Workflow

1. Capture prod landing + one section (e.g. Mortgage) — screenshot + module list from DOM/network.
2. Capture Pi/local same section — same viewport (1280×900 default).
3. Tabulate deltas (blocker / major / minor / nit).
4. Cross-check roadmap gap list; mark items verified fixed or still open.
5. Recommend owner: **dashboard-agent** (server/API/html), **site-shell-agent** (site assets only).

## Return format

| Column | Content |
|--------|---------|
| Area | e.g. Routing, Modules, API |
| Production | observed |
| Local/Pi | observed |
| Severity | blocker / major / minor / nit |
| Owner | dashboard / site-shell / ingest |
| Evidence | screenshot filenames |

## Anti-patterns

- Using production as sole verification for merge (forbidden by repo rules).
- Filing functional bugs here without trying **deep-browser-explore** repro steps.
- Inventing local display names for public taxonomy nodes.
- Parity pass while Pi shell git is behind `origin/main`.

## Related

- `deep-browser-explore` — interaction QA, ship-bar evidence
- `dashboard-agent` — implements parity fixes in AR-local
- `site-shell-agent` — australianrates `site/` only
- `pi-deploy-agent` — sync shell checkout on Pi
