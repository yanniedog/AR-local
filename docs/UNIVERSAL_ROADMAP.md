# AR-local Universal Roadmap

This is the shared roadmap for LLM agents working on AR-local. Treat it as the operating contract for changes that affect Pi runtime, dashboard parity, data durability, and ship workflow.

## North Star

AR-local is the LAN-hosted, self-contained local runtime for Australian CDR data. On the Raspberry Pi it must serve the dashboard continuously at:

- `http://<pi-ip>:8808/`
- `http://ar.local:8808/` when local DNS or mDNS is configured for the Pi

The dashboard must use real generated artifacts only, with banking as the current priority. Energy remains secondary unless the user explicitly reopens it.

## Current Deployed Shape

The current Pi deployment is portable-root based. The systemd service does not run from the old bootstrap checkout under `/home/pi`; it runs from the portable tree:

- authoritative app checkout: `/srv/ar-local/AR-local`
- authoritative AustralianRates shell checkout: `/srv/ar-local/australianrates`
- authoritative durable data root: `/srv/ar-local/data`
- durable run DBs: `/srv/ar-local/data/runs/<date>/_exports/local-cdr.sqlite`
- dashboard service: `ar-local-dashboard.service`
- dashboard bind: `0.0.0.0:8808`

### Authoritative service checkout

Before declaring the Pi updated, run:

```sh
systemctl cat ar-local-dashboard.service
```

Check these fields:

- `WorkingDirectory`: the checkout where `git rev-parse HEAD` must equal `origin/main`.
- `ExecStart`: the Python script path, `--runs` root, `--site-root`, host, and port that the live dashboard actually uses.

Updating `/home/pi/AR-local` alone is not enough if `WorkingDirectory` points at `/srv/ar-local/AR-local`.

## Non-Negotiables

- Work from fresh `origin/main` on a distinct branch.
- Follow `WORKFLOW.md` before opening or merging any PR.
- Keep the Pi deployed copy equal to GitHub `main`; no unmerged topic branch is a deployed runtime.
- Keep generated artifacts indefinitely unless the user explicitly changes retention.
- Use RAM-backed staging for high-churn ingest/build work on the Pi, then atomically copy completed `_exports` into durable storage.
- Use AustralianRates `site/` assets and ribbon builders as the canonical dashboard source. Do not fork public hierarchy labels, tier ordering, or node semantics into AR-local unless the public site exposes no equivalent.
- Acceptance uses local dashboard verification, not Cloudflare or `www.australianrates.com.au`.

## Portable Runtime Model

The portable root is the single tree that can move from microSD to USB SSD or Pi 5 SSD HAT storage:

```text
/srv/ar-local/
  AR-local/
  australianrates/
  data/
    runs/<date>/_exports/
    state/
```

Services must be rendered against this portable root and must not bake in microSD-specific paths. To migrate to SSD:

1. Stop `ar-local-dashboard.service` and `ar-local-daily.timer`.
2. Copy `/srv/ar-local` to the SSD mount with ownership and permissions preserved.
3. Mount the SSD at `/srv/ar-local`, or reinstall the units with the SSD path as the portable root.
4. Start the timer and dashboard service.
5. Verify `git rev-parse HEAD` equals `origin/main` and run `npm run verify:local -- --base-url=http://127.0.0.1:8808/`.

If a separate `/home/pi/AR-local` checkout exists, treat it as a bootstrap/admin convenience unless the authoritative service checkout proves the installed unit is using it.

## LAN Availability

The dashboard server must bind to `0.0.0.0` on port `8808` for Pi service use and for manual LAN launches. All browser assets and API calls must remain same-origin relative URLs so every PC on the LAN can load the dashboard from the Pi IP address.

Pi setup should also provide a stable LAN name:

- Preferred: router DHCP reservation for the Pi MAC address to keep the current fixed IP.
- `ar.local`: use Avahi/mDNS or a router DNS override pointing `ar.local` to the Pi IP.
- Verification: from another PC, open `http://<pi-ip>:8808/` and `http://ar.local:8808/api/latest`.

## Dashboard Parity

Parity means the local dashboard uses the same public shell, branding, hierarchy taxonomy, compact node labels, tier ordering, and ribbon behavior as AustralianRates.

Current source of truth:

- Static public shell: sibling `australianrates/site/`
- Ribbon formatting: `/site/ar-ribbon-format.js`
- Ribbon tree construction: `/site/ar-ribbon-tree.js`
- Local row adapter: `dashboard/cdr-ribbon-map.js`
- Local hierarchy renderer: `dashboard/hierarchy.js`

Rules for future agents:

- Prefer `window.AR.ribbon.ribbonTierFieldsForSection()` and `window.AR.ribbon.buildRibbonTierTree()` for visible banking hierarchy.
- Keep `dashboard/cdr-taxonomy-tree.js` as fallback or diagnostic support, not the primary visible banking tree.
- When public AustralianRates changes hierarchy fields or labels, update the local row adapter and verify identical node lists against the public asset behavior.
- Do not invent local display names for canonical public nodes.
- Preserve valid accessibility attributes; branch rows use `aria-expanded="true"` or `"false"`.

## Historical Ribbon Values

The ribbon must surface historical banking values from retained SQLite exports. The server exposes `/api/banks/history`, built from the latest retained `runs/*/_exports/local-cdr.sqlite` files, and the client indexes historical rows by dataset and product identity. The HTTP payload is intentionally bounded to a recent run window while the artifacts themselves remain retained indefinitely.

Current implemented behavior:

- `dashboard/app.js` loads `/api/banks/history`, normalizes retained rows once, and indexes them by dataset/product identity.
- `dashboard/chart.js` renders the banking chart from a `bank-history` model using retained run dates.
- The dashboard exposes `30D`, `90D`, `180D`, `1Y`, and `All` history windows.
- The right-hand `Current slice` panel remains based on the AustralianRates ribbon tree for the current visible slice.
- Hierarchy rows show prior/latest history deltas when at least two retained run dates exist for the matching products.
- With only one retained run, a single-date ribbon/point column is expected. Do not fabricate a second date to make the chart look historical.

A retained run date is a valid `YYYY-MM-DD` child directory under the active service `--runs` root that contains `_exports/local-cdr.sqlite`; for the portable Pi service this is normally `/srv/ar-local/data/runs/<date>/_exports/local-cdr.sqlite`. New greenfield installs may legitimately have one retained run until daily automation accumulates more.

Future improvements should:

- Keep history reads in memory where practical; avoid repeated microSD churn.
- Prefer compact history payloads over shipping full `details_json`.
- Extend hierarchy history only through public tier semantics; do not fork local node meanings.
- Verify at least two retained runs when changing historical display logic where practical, but accept a one-run Pi as an initial greenfield state.

## Banks-First Work Queue

1. Keep banking ingest/export healthy on Pi.
2. Keep `Mortgage`, `Savings`, and `TD` dashboard sections parity-aligned with AustralianRates.
3. Keep historical ribbon values populated from retained DB exports.
4. Keep LAN access stable on Pi IP and `ar.local`.
5. Keep SSD portability documentation and systemd unit rendering current.
6. Only revisit Energy after the user explicitly asks.

## Verification Checklist

Before PR:

```sh
python -m py_compile cdr_dashboard_server.py cdr_outputs.py cdr_daily.py pi_daily_sync.py
node --check dashboard/app.js
node --check dashboard/chart.js
npm run verify:local -- --base-url=http://127.0.0.1:<port>/
```

For dashboard UI changes, use Browser MCP or an equivalent real browser check against the running local dashboard. Confirm the chart, history-window controls, provider logos, and `Current slice` hierarchy render together.

On Pi after merge/setup:

```sh
# First identify the authoritative service checkout and --runs root.
systemctl cat ar-local-dashboard.service
cd /srv/ar-local/AR-local
git rev-parse HEAD
git rev-parse origin/main
node --version
npm --version
gh --version
python3 --version
git --version
systemctl status ar-local-dashboard.service
systemctl status ar-local-daily.timer
npm run verify:local -- --base-url=http://127.0.0.1:8808/
curl -fsS http://127.0.0.1:8808/api/latest
curl -fsS http://127.0.0.1:8808/api/banks/history
```

The `HEAD` check must be run in the authoritative service checkout, normally `/srv/ar-local/AR-local`.

From another LAN PC:

```sh
curl -fsS http://<pi-ip>:8808/api/latest
curl -fsS http://ar.local:8808/api/latest
```

## Handoff Discipline

Every agent should leave the next agent with:

- Branch name and PR URL.
- Exact commands run and failures, if any.
- Whether Pi deployment was updated to GitHub `main`.
- Which Pi checkout the service is using, from the authoritative service checkout check.
- Current dashboard URL and verification result.
- Current retained history run count from `/api/banks/history`.
- Any parity gap deliberately deferred.
