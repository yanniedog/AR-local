---
name: deep-browser-explore
description: >-
  Deep visual and interaction QA via Browser MCP (user-browser_agent_cursor):
  navigate, snapshot DOM, click/type/hover/scroll, capture screenshots,
  console and network, structured findings for AR-local dashboard and parity checks.
---

# Deep browser explore (AR-local)

Browser-first exploration for **real URLs** on the local CDR dashboard or Pi host. Complements HTTP smoke (`npm run verify:local`); does **not** replace it for ship-bar sign-off.

**Read MCP tool schemas every session** before calling tools — list descriptors under the active Cursor project's `mcps/user-browser_agent_cursor/tools/` folder (project slug varies; use the MCP file system path shown in agent context).

## When to use

- Dashboard UI QA after HTML/JS/CSS changes (`dashboard/**`, chart, hierarchy rail, section cards).
- Regression after Pi deploy or local server restart.
- **Economic Data** section, hierarchy drill-down, provider filter, chart workspace resize.
- Parity spot-check vs AustralianRates public shell (comparison only — **sign-off stays local/Pi** per repo rules).
- User or chief asks for evidence beyond `verify:local` (console errors, layout, interaction state).

## Invocation phrases

- **"deep browser explore"**
- **"browser QA pass"**
- **`/deep-browser-explore`**

Chief may delegate: *Follow `.cursor/skills/deep-browser-explore/SKILL.md` on `<base-url>`; return findings table + artifact paths.*

## Prerequisites

| Requirement | Notes |
|-------------|--------|
| MCP server | `user-browser_agent_cursor` enabled in Cursor |
| Base URL | Running dashboard with valid `/api/latest` (see Preflight) |
| `projectId` | Use repo name e.g. `"AR-local"` for `session_create` |
| Schemas | Re-read tool JSON descriptors each session (API may change) |

### Preflight (mandatory)

1. `npm run verify:local -- --base-url=<url>/` — must exit **0** before deep UI pass (or document why waived).
2. If page shows only `Error: /api/latest returned 404`, **stop** — fix exports/server; browser pass will have no nav/hierarchy.
3. Prefer Pi or local instance with real ingest data, not an empty exports path.

## MCP tool inventory (`user-browser_agent_cursor`)

| Tool | Purpose | Key parameters |
|------|---------|----------------|
| `session_create` | Start Playwright session | `projectId` (required), `browser` (`chromium`/`firefox`/`webkit`), `headless`, `mode` (`deterministic`/`human`), `viewport`, `emulation`, `manifestPath` |
| `session_set_emulation` | Resize / mobile tablet | `viewport`, `emulation`, `preserveUrl` |
| `session_close` | End session | `sessionId` |
| `navigate` | Open URL | `url`, `waitUntil` (`domcontentloaded`/`load`/`networkidle`) |
| `click` | Click element | CSS `selector`, `timeoutMs` |
| `type` | Fill input | `selector`, `text`, `clearFirst` |
| `hover` | Hover | `selector` |
| `select` | `<select>` option | `selector`, `value` |
| `scroll` | Window scroll | `x`, `y` (pixel offsets) |
| `wait_for` | Wait for element or idle | `selector` + `state` (`visible`/`hidden`/…), or `strategy` (`locator`/`networkidle`/`renderready`) |
| `snapshot_dom` | Full HTML dump to artifact file | `sessionId` |
| `screenshot` | PNG evidence | `fullPage`, `name` (use `.png` suffix) |
| `console_capture` | Browser console log export | `sessionId` |
| `network_capture` | Network log export | `sessionId` |
| `trace_start` / `trace_stop` | Playwright trace | `name` on stop |
| `upload` / `download` | File inputs / download triggers | `selector`, paths |

### Not available (gaps)

- No **`evaluate`** / run arbitrary JS in page.
- No **keyboard** tools (`press`, `Tab`, `Enter`, `Escape`) — use clickable controls or `type` on focused inputs.
- No **coordinate click** — only CSS `selector` (Playwright locators; strict mode if multiple matches).
- No accessibility **ref** channel separate from DOM — derive selectors from `snapshot_dom` or stable attributes (`data-section`, `aria-label`, `role=button`).
- `scroll` is **viewport pixel** scroll, not “scroll into view” for a selector (use `wait_for` + layout or tab focus via click).
- `screenshot` without a proper `name` may error (`unsupported mime type "null"`); always pass `name` ending in `.png`.
- `trace_stop` may fail on some hosts; treat trace as optional if `screenshot` + `snapshot_dom` succeed.

Call tools via **`CallMcpTool`** with `server: "user-browser_agent_cursor"` and `toolName` matching schema `name`.

## AR-local defaults

| Target | URL |
|--------|-----|
| Local dashboard | `http://127.0.0.1:<port>/` (port from `cdr_dashboard_server.py` stdout; often `8808`) |
| Pi / tunnel | See **Pi dashboard URLs** in `docs/UNIVERSAL_ROADMAP.md` (LAN/Tailscale IP, SSH tunnel `127.0.0.1:18808`) |

**Sections to cover:** Mortgage, Savings, TD (Term Deposits), Economic Data (`data-section` / `data-section-card`). No non-banking CDR UI should be present.

**Do not** use `www.australianrates.com.au` as acceptance sign-off unless the task is explicit **parity comparison**; ship bar still uses local/Pi + `verify:local`.

### Stable selectors (dashboard)

| UI | Selector hint |
|----|----------------|
| Header section | `button.site-header-segment-link[data-section="Mortgage"]` |
| Section cards | `button[data-section-card="Savings"]` |
| Hierarchy branch | `[aria-label^="Expand "]` — use **unique** label, e.g. `[aria-label="Expand Investor"]` (strict mode rejects ambiguous CSS) |
| Hierarchy row | `.ar-report-infobox-trow--branch`, `#hierarchy` |

After expand, confirm `aria-expanded="true"` on the row in a follow-up `snapshot_dom`.

## Workflow phases

### 1. Setup

```
session_create(projectId, browser=chromium, headless=true, viewport={width:1280,height:900})
trace_start(sessionId)   # optional
navigate(sessionId, baseUrl, waitUntil=networkidle)
wait_for(sessionId, strategy=networkidle)
snapshot_dom(sessionId)    # confirm not error-only body
screenshot(sessionId, name="00-landing.png")
```

Dismiss modals/cookie banners if present (click close control from snapshot). Set desktop viewport first; repeat critical paths at `session_set_emulation` mobile if requested.

### 2. Structural map

From `snapshot_dom` artifact + `screenshot`:

- Header segments, footer links, section cards.
- Chart workspace, `#hierarchy`, resizer, breadcrumbs.
- Forms, filters, tables — list interactive nodes with proposed selectors.

Record a **coverage map** (visited vs blocked).

### 3. Deep traverse

Use BFS or DFS over interactive elements with a **depth budget** (default: 3 hierarchy levels, all top-level sections).

Queue: buttons, `[role=button]`, links, tabs, section cards, hierarchy branches, chart controls.

Skip: external mailto, duplicate hash-only nav unless testing SPA routing.

### 4. Per-interaction protocol

For each queued control:

1. **Before:** `screenshot` + note URL/title from last tool `page_state`.
2. **Action:** `click` / `type` / `hover` / `select` — unique selector only.
3. **Wait:** `wait_for(strategy=networkidle)` or `wait_for(selector, state=visible)`.
4. **After:** `screenshot`, `snapshot_dom` if DOM structure may change.
5. **Diagnostics:** `console_capture`; on failure or 4xx/5xx suspicion, `network_capture`.
6. **Record:** state change (section title, breadcrumb, chart series, expanded branch).

### 5. Mouse-like interaction

- Prefer **semantic selectors**: `aria-label`, `data-section`, `data-local-hierarchy-path`, `role`.
- Use `hover` before menus that open on hover.
- Avoid coordinate clicks; MCP has no x/y click.
- When multiple matches: narrow with `aria-label`, `data-ribbon-tree-path`, or nth-child only as last resort.

### 6. Keyboard (workarounds)

No keypress MCP. Approximate:

- **Focus:** `click` on `tabindex="0"` controls.
- **Activate:** `click` (same as Enter for buttons).
- **Dismiss modal:** click backdrop close or visible Cancel — no Escape key.
- **Tab order:** not systematically testable without keyboard API.

### 7. Report

Deliver a findings table and coverage summary.

| Area | Action | Expected | Actual | Severity |
|------|--------|----------|--------|----------|
| Mortgage / hierarchy | Expand Investor | Child rows visible, `aria-expanded=true` | … | blocker / major / minor / nit |

Also include:

- Base URL, session/artifact root path, screenshot filenames.
- Console: error/warning counts from `console_capture`.
- Untested areas and blockers (missing API, auth, flaky trace).

**Severity:** blocker = broken core flow; major = wrong data/UI; minor = polish; nit = copy/spacing.

## Anti-patterns

- Claiming **"tested"** without `screenshot` or `snapshot_dom` evidence.
- Skipping **console_capture** when interactions fail or chart is empty.
- Using **production** australianrates.com as the only verification environment.
- Ambiguous selectors that trip Playwright **strict mode violation**.
- Deep browse against local server with **`/api/latest` 404** (empty error page).
- Ignoring `verify:local` failures while filing cosmetic UI tickets.

## Session teardown

```
trace_stop(sessionId, name="…")   # optional; may fail harmlessly
session_close(sessionId)
```

## Relation to other checks

| Check | Role |
|-------|------|
| `npm run verify:local` | HTTP 200 smoke — required for ship bar |
| This skill | Interaction, layout, console, visual regression evidence |
| `browser-first-beta-tester` (Codex) | Same philosophy; this skill is AR-local scoped with dashboard selectors |

## Minimal demo script (chief / CI spot-check)

On Pi or healthy local URL:

1. `navigate` → base URL
2. `click` `button.site-header-segment-link[data-section="Mortgage"]`
3. `click` `[aria-label="Expand Investor"]` (or first branch label from snapshot)
4. `screenshot` `name="demo-hierarchy.png"`
5. `console_capture`

Pass: screenshots exist, hierarchy expands, no uncaught errors in console export for the exercised path.

## Optional helper script

No required repo script — MCP-only workflow is sufficient. Add `scripts/deep-browser-explore.mjs` only if you need a checklist emitter; not part of the default ship bar.
