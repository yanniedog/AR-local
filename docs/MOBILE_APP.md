# AR Rates — mobile app + daily payload

A polished iOS + Android app (Expo / React Native) for the AR-local CDR rates data.
The Raspberry Pi builds a compact daily **payload** and publishes it to a rolling
**GitHub Release**; the app downloads it, serves everything offline, and fires local
notifications when rates move.

```text
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
  `brands` (embedded canonical logo where available, plus monogram short-code + colour
  fallback; no external CDN) + `rba[]`.
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
2. Install it on the Pi (writes `/etc/ar-local/app-payload.env`, mode 0600 — never
   committed). The daily + watchdog service units already reference this file via
   `EnvironmentFile=-/etc/ar-local/app-payload.env`:

   ```bash
   sudo sh deploy/pi/install-app-payload-token.sh github_pat_xxx
   ```

3. Re-render the service units so the new `EnvironmentFile` line lands, then reload
   (service-unit changes are applied by the installer, not the auto-deploy watchdog):

   ```bash
   sh deploy/pi/install-pi-systemd.sh /srv/ar-local
   sudo systemctl daemon-reload
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

Expo SDK 54 + expo-router + TypeScript. Offline-first: it seeds from a bundled sample,
then upgrades to the live GitHub payload; all screens serve from a local cache. It does
**not** need a local server and works off-LAN — the data comes from the GitHub Release.

The UI mirrors the **AR-local dashboard**: a **ribbon** (rate distribution: min / median /
mean / max with the RBA cash-rate marker on home loans) and the **drill-down hierarchy**
driven by each row's `taxonomy_path` (e.g. Owner-occupied → Principal & interest →
Variable → 70–80% LVR). You drill categories until the leaf, then tap a product for full
detail. The flat search/sort/filter/compare list is still available (the search icon).

Features: Home dashboard (section ribbon + hero rate + RBA chart + top categories + best
rate), Browse drill-down, scoped Search (sort, filters, compare 2–4), Product detail
(every rate row + fees/features/eligibility/constraints), Watchlist, Lenders, Trends, and
Settings. Local notifications fire on best-rate moves, RBA changes, and watchlisted moves.

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

## 4. Run it on your phone / iPad

The live release is already published (`app-payload-latest`), so the app pulls **real
CDR data from GitHub over the internet** — no local server, works off your LAN. The
bundled sample is just the instant-on fallback until the first download completes. Once
the Pi's daily publish is enabled (§2), the data refreshes itself each day.

### Option A — Development build (recommended; full features, not Expo-Go-version-bound)

A dev build embeds the exact SDK, so it never hits "Expo Go needs SDK NN", and background
refresh + notifications work. Needs a free **Expo account**; iPad also needs Apple Developer.

```bash
cd mobile
npm i -g eas-cli && eas login
eas build --profile development --platform android   # installable dev-client APK
eas build --profile development --platform ios       # iPad: installs via the build link / TestFlight
```
Install the build on the device, then run `npx expo start --dev-client` on your computer
and open it from the dev client (or scan its QR). `expo-dev-client` is already a dependency.

### Option B — Expo Go (fastest; no accounts, both devices)

Best for trying the UI/data immediately. One caveat: OS background refresh needs a real
build (Option A), but everything else — drill-down, ribbon, search, filters, charts,
compare, watchlist, detail, theme, offline cache, "Refresh now" — works in Expo Go.
Expo Go must support the project's SDK (54); install the current Expo Go from the store.

### Option A — Expo Go (fastest; no accounts, both devices)

Best for trying the UI/data immediately. One caveat: background refresh needs a real
build (Option B), but everything else — browse, filters, charts, compare, watchlist,
detail, theme, offline cache, and tapping "Refresh now" — works in Expo Go.

1. On the **iPad** install **Expo Go** from the App Store; on the **Android phone**
   install **Expo Go** from the Play Store.
2. On your computer:
   ```bash
   cd mobile
   npm install
   npx expo start            # shows a QR code
   # if phone and computer aren't on the same Wi-Fi:
   npx expo start --tunnel
   ```
3. **Android:** open Expo Go → "Scan QR code" → scan the terminal QR.
   **iPad:** open the Camera app → point at the QR → tap the "Open in Expo Go" banner.

### Option C — Standalone preview/production builds with EAS

Needs a free **Expo account** (`eas login`). Android needs no store account; iPad
needs an **Apple Developer** membership ($99/yr) to install a real build.

```bash
cd mobile
npm i -g eas-cli && eas login
eas build:configure          # one-time; links the project to your Expo account
```

**Android phone — direct-install APK (no Google account needed):**

```bash
eas build --platform android --profile preview
```

EAS prints a build URL; open it on the phone (or scan its QR) and tap **Install** the
`.apk`. Allow "install from unknown sources" if prompted.

**iPad — via TestFlight (recommended) or ad-hoc:**

```bash
eas build --platform ios --profile production
eas submit --platform ios        # uploads to App Store Connect → TestFlight
```

Then add yourself as an internal tester in App Store Connect and install via the
**TestFlight** app on the iPad. (Ad-hoc alternative: register the iPad's UDID with
`eas device:create`, then `eas build -p ios --profile preview`.)

`eas.json` defines `development` / `preview` / `production` profiles. The
`bundleIdentifier` (`com.yanniedog.arlocalrates`) / Android `package` live in
`app.json` — change them if you use different store identifiers.

### Pointing at live data

By default the app reads `app.json` → `expo.extra.manifestUrl`
(`…/releases/download/app-payload-latest/manifest.json`). Until the Pi publishes (or
you run the `app-payload-publish` Action to seed it), the app serves the bundled
sample and shows a "sample data" banner — that's expected.

## 5. Store submission (later)

```bash
eas build --platform all --profile production
eas submit --platform ios        # App Store Connect
eas submit --platform android     # Google Play
```

## Notes & follow-ups

- Real bank logos: the Pi embeds the canonical AustralianRates PNG logo pack into
  `core.brands` as compact data URIs, so logos render offline without an external CDN.
  Lenders outside the pack retain deterministic coloured monograms.
- Remote push (vs the current local notifications) would need a device-token store.
- Per-product rate history could be added as a future payload tier from
  `/api/banks/history`.
