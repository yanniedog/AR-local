# AR-local Universal Roadmap

This is the shared roadmap for LLM agents working on AR-local. Treat it as the operating contract for changes that affect Pi runtime, dashboard parity, data durability, and ship workflow.

## North Star

AR-local is the LAN-hosted, self-contained local runtime for Australian CDR data. On the Raspberry Pi it must serve the dashboard continuously at:

- `http://<pi-ip>:8808/`
- `http://ar.local:8808/` when local DNS or mDNS is configured for the Pi

The dashboard must use real generated artifacts only, with banking as the current priority. Energy remains secondary unless the user explicitly reopens it.

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

The ribbon must surface historical banking values from retained SQLite exports. The server exposes `/api/banks/history`, built from `runs/*/_exports/local-cdr.sqlite`, and the client indexes historical rows by dataset and product identity.

Future improvements should:

- Keep history reads in memory where practical; avoid repeated microSD churn.
- Prefer compact history payloads over shipping full `details_json`.
- Show history in the hierarchy without changing public tier semantics.
- Verify at least two retained runs when changing historical display logic.

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
npm run verify:local -- --base-url=http://127.0.0.1:<port>/
```

On Pi after merge/setup:

```sh
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
- Current dashboard URL and verification result.
- Any parity gap deliberately deferred.
