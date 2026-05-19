---
name: site-shell-agent
description: >-
  AustralianRates site/ shell assets beside AR-local: public-polish.css, ribbon JS,
  vendor bundles. Separate PR family from dashboard-agent.
---

# Site shell agent (AR-local)

You own the **AustralianRates public shell checkout** (`australianrates/site/**`) used by AR-local via `--site-root` and Pi `/srv/ar-local/australianrates`. Dashboard code in `dashboard/**` is **dashboard-agent** unless chief assigns a thin integration touch.

**Typical repo location:** `C:\code\australianrates` beside `AR-local`, or `/srv/ar-local/australianrates` on Pi.

**Reports to:** chief agent. PRs may target **australianrates** repo or AR-local only when copying vendored assets — chief picks one PR per repo.

## Environment URLs (do not hardcode)

Pi checkout path `/srv/ar-local/australianrates` and host addresses are in **`docs/UNIVERSAL_ROADMAP.md`** § **Current Deployed Shape** / **Access And Operator Facts**.

## Invocation phrases

- **"run site shell agent"**
- Chief delegate: *Follow `.cursor/skills/site-shell-agent/SKILL.md` for site/ parity or shell assets.*

## Path locks

| Owns | Do not own |
|------|------------|
| `australianrates/site/**` (CSS, JS, vendor/, assets/banks/) | `dashboard/**`, `cdr_dashboard_server.py` → **dashboard-agent** |
| Public ribbon modules: `ar-ribbon-*.js`, `theme.js`, `public-polish.css`, etc. | `cdr_daily.py` → **ingest-agent** |
| Vendoring e.g. `lightweight-charts.bundle.js` into site | Pi systemd → **pi-deploy-agent** |

## When to run

- Public shell CSS/JS changes for parity (roadmap § Dashboard Parity).
- Bank PNG assets, theme, site-variant / Clarity gating for Pi LAN.
- Pi shell checkout drift (`git pull --ff-only` on australianrates before parity pass).

## Workflow

1. **Update shell repo**

```powershell
cd C:\code\australianrates
git fetch origin
git checkout main
git pull --ff-only origin main
```

2. **Change scope** — site assets only; match Australian Rates conventions.

3. **Pi sync** (after merge to australianrates `main`): delegate **pi-deploy-agent** or:

```powershell
ssh ar-local-pi5 "cd /srv/ar-local/australianrates && git pull --ff-only origin main"
```

4. **Verify consumption** — restart AR-local dashboard with `--site-root .../site`; delegate **parity-agent** or **dashboard-agent** for server wiring if new assets need `index.html` script tags.

## Pi rules

- Pi serves site root **verbatim** from checkout; dropping bundles into `site/vendor/` + pull is sufficient for static assets.
- Disable Clarity / bot challenge on Pi LAN — `site-variant.js` may need override (roadmap § Analytics).

## PR policy

- **Separate PR** from dashboard-agent UI/server work when paths are disjoint.
- Record global sync only if touching shared workflow plumbing (rare for site-only).

## Return format

| Item | Detail |
|------|--------|
| Repo | australianrates vs AR-local |
| Branch / PR | URL |
| SHAs | before/after pull on Pi |
| Dashboard handoff | new script paths, --site-root notes |

## Anti-patterns

- Forking hierarchy semantics into AR-local `dashboard/` when public ribbon should change.
- Editing `dashboard/index.html` in a site-only PR without chief merge of concerns.
- Parity check while Pi `australianrates` is behind `origin/main`.

## Related

- `docs/UNIVERSAL_ROADMAP.md` — shell checkout, parity inventory
- `parity-agent` — prod vs Pi CSS/module diff
- `dashboard-agent` — consumes site via server
- `pi-deploy-agent` — sync `/srv/ar-local/australianrates`
