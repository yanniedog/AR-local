# AR Rates — mobile app + daily payload

A polished iOS + Android app (Expo / React Native) for the AR-local CDR rates data.
The Raspberry Pi builds a compact daily **payload** and publishes it to a rolling
**GitHub Release**; the app downloads it, serves everything offline, and fires local
notifications when rates move.

```
Pi daily ingest ──► app_payload build ──► GitHub Release (tag: app-payload-latest)
                                              ├─ manifest.json      (tiny; polled first)
                                              ├─ core-<date>.json.gz (rates + ribbon + brands + RBA)
                                              └─ details-<date>.json.gz (fees/features/eligibility/constraints)
                                                        │
                                          mobile app ◄──┘  download → inflate → cache → serve offline
```

## 1. Payload contract (`schema_version: 1`)

The builder (`app_payload.py`) reads the already-generated, compact
`runs/<date>/_exports/dashboard-cache/<date>/banks.json` (plus `latest.json` for
counts and `dashboard/rba-cash-rate.js` for the RBA series) — no SQLite, no running
server, so it works in the daily pipeline and in CI.

- **`manifest.json`** — `{ schema_version, run_date, generated_at, app_min_version,
  repo, tag, counts, schedule, files }`. `files.core` / `files.details` each carry
  `{ name, bytes, sha256, url }` with the stable release download URL. The app polls
  this first and re-downloads only when `run_date` / `sha256` changed.
- **`core-<date>.json.gz`** — `sections.{Mortgage,Savings,TD}.{rates[],ribbon}` +
  `brands` (monogram short-code + colour per lender, no external CDN) + `rba[]`.
  Each rate row is the dashboard's `BANK_SECTION_COLUMNS` set plus `comparison_rate`.
  Filtering mirrors the dashboard (Mortgage = lending & non-DISCOUNT; deposits otherwise).
- **`details-<date>.json.gz`** — per-`product_key` `{ description, last_updated, fees,
  features, eligibility, constraints }`. Downloaded lazily after `core`.

Content files are **content-hashed and contain no wall-clock field**, so a same-day
rebuild (e.g. the watchdog rerun) produces identical bytes and the app skips a
needless re-download.

Build it locally and inspect:

```bash
python app_payload.py build --exports runs/2026-05-19/_exports \
  --out runs/2026-05-19/_exports/app-payload
python -m pytest tests/test_app_payload.py -q
```

## 2. Pi setup — enable the daily publish

Publishing is **opt-in and non-fatal**: the daily ingest never fails because of a
payload error, and with no token the builder just builds locally and skips the upload.

1. Create a GitHub **fine-grained PAT** scoped to `yanniedog/AR-local` with
   **Contents: Read and write** (covers Releases).
2. Put it (and the opt-in flag) in an env file the daily service reads, e.g.
   `/etc/ar-local/app-payload.env`:

   ```ini
   AR_LOCAL_APP_PAYLOAD=1
   GH_TOKEN=github_pat_xxx
   ```

3. Reference it from the daily unit and reload:

   ```ini
   # deploy/pi/ar-local-daily.service  (and the watchdog service)
   [Service]
   EnvironmentFile=-/etc/ar-local/app-payload.env
   ```

   ```bash
   sudo systemctl daemon-reload
   sudo systemctl restart ar-local-daily.timer
   ```

4. (Optional) Confirm with one manual run:

   ```bash
   AR_LOCAL_APP_PAYLOAD=1 GH_TOKEN=... python3 pi_daily_sync.py --banks-only --force
   # → "pi_daily_sync: app payload published (run_date=YYYY-MM-DD)"
   curl -fsSL https://github.com/yanniedog/AR-local/releases/download/app-payload-latest/manifest.json
   ```

`gh` must be installed on the Pi (`sudo apt install gh`). The release/tag is created
automatically on first publish.

**Bootstrap before the Pi runs:** trigger the `app-payload-publish` GitHub Action
(Actions tab → Run workflow) to seed the release from the committed sample so the app
resolves the release URL immediately; the Pi overwrites it on its next ingest.

## 3. The app (`mobile/`)

Expo SDK 52 + expo-router + TypeScript. Offline-first: it seeds from a bundled sample,
then upgrades to the live GitHub payload; all screens serve from a local cache.

Features: Home (RBA cash rate + per-category bests), Browse (search, sort, filters,
rate-distribution ribbon, virtualized lists), Product detail (rates, fees, features,
eligibility, constraints), Compare (2–4 side-by-side), Watchlist, Lenders, Trends, and
Settings (theme, default category, alert threshold, Wi-Fi-only refresh, cache).
Local notifications fire on best-rate moves, RBA changes, and watchlisted-product moves.

```bash
cd mobile
npm install
npm run typecheck && npm run lint && npm test
npx expo start            # press i / a, or scan with Expo Go
```

Config lives in `app.json` → `expo.extra` (`repo`, `releaseTag`, `manifestUrl`).

### Regenerate the bundled sample / icons

```bash
python app_payload.py build --exports runs/<date>/_exports --out runs/<date>/_exports/app-payload
cd mobile && npm run sample      # decompress payload → assets/sample/*.json
npm run icons                    # regenerate icon/splash from scripts/make-icons.py
```

## 4. Store builds (EAS)

Requires your Expo, Apple Developer, and Google Play accounts.

```bash
cd mobile
npm i -g eas-cli && eas login
eas build:configure
eas build --platform android --profile preview     # internal APK
eas build --platform all --profile production
eas submit --platform ios     # / android
```

`eas.json` defines `development` / `preview` / `production` profiles. Update the
`bundleIdentifier` / `package` in `app.json` if you use different store identifiers.

## Notes & follow-ups

- Real bank logos: v1 uses branded monogram avatars (deterministic colour + short code
  from `dashboard/ar-bank-brand.js`) to stay off the deprecated `australianrates.com`
  CDN. A future tier could publish a `logos/` set into the release.
- Remote push (vs the current local notifications) would need a device-token store.
- Per-product rate history could be added as a future payload tier from
  `/api/banks/history`.
