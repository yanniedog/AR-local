# AR-local — Mobile App & Daily Publishing: LLM Handoff

> A self-contained guide so another agent (Claude, ChatGPT, Cursor/Composer, etc.) can
> continue this work **without prior context**. Last updated **2026-06-09**.
> If anything here disagrees with the code, the code wins — verify before acting.

---

## 0. One-paragraph summary

AR-local is a CDR (Australian open-banking) **bank interest-rate pipeline**. A Raspberry
Pi runs a daily ingest and serves a web dashboard. We built a **mobile app** (Expo / React
Native) that does **not** talk to the Pi or any server: the Pi packages a compact daily
**payload** and uploads it to a **GitHub Release**; the app **downloads that payload over
the public internet and renders everything locally** (works offline, off-LAN, worldwide).
The goal is for the app to **look and behave like the web dashboard** at
`http://100.78.28.10:8808/`.

```
Raspberry Pi (daily, 01:00 Australia/Hobart)  GitHub                         Mobile app (anywhere)
────────────────────────────────              ──────                         ─────────────────────
pi_daily_sync.py --banks-only                 Release tag                    on launch / pull-to-refresh:
  → _exports/dashboard-cache/<date>/          "app-payload-latest"            1. GET manifest.json
       banks.json + latest.json          ┌──► ├─ manifest.json         ──┐    2. if run_date newer → GET
  → app_payload.build_and_publish_dual   │    ├─ core-<date>-<sha>.gz   │       core + details (gzip),
       dated tag + rolling latest         │    └─ details-<date>-<sha>.gz│       inflate, cache to disk
       (AR_LOCAL_APP_PAYLOAD + GH_TOKEN) ─┘   + app-payload-<date> tags └──► 3. render all screens locally
                                                                              4. diff vs previous → notify
```

---

## 1. Current state (what's done / working)

- **App** (`mobile/`): Expo **SDK 54**, expo-router, TypeScript. Dashboard-style UI
  (rate-distribution **ribbon** + **drill-down hierarchy** + product detail). Pulls the
  **live GitHub payload**; seeds from a bundled sample on first launch. Merged in PRs
  **#154** (app + pipeline), **#155** (SDK 54 + 0 npm vulns), **#156** (dashboard UI + live
  data). `npm audit` = 0; tsc/lint/jest all green.
- **Pi publishing**: Pi is online (Tailscale), on latest `main`, and **auto-publishes the
  payload every day** (token installed — verified live, `run_date` 2026-06-08 is on the
  release). Daily timer next runs **01:00 local** (`Australia/Hobart` on ar-local-pi5).
- **EAS**: project `@yannieyannies-team/ar-local-rates` (`projectId`
  `69c08d63-b618-43f1-86b9-2556eef82104`). An **Android development build** has been built
  and is installable. PR **#157** persists the EAS `owner`/`projectId` in `app.json`
  (may still be in review when you pick this up).
- **iOS build**: not done — needs an Apple Developer account + device UDID.

---

## 2. Likely next tasks (what the user will ask) — playbooks

### Task A — "Make sure the Pi is actually uploading daily CDR data to GitHub each day"

The whole daily path already exists and is enabled. To **verify** it's working:

1. **Is the live release fresh?** (no Pi access needed)
   ```bash
   curl -fsSL https://github.com/yanniedog/AR-local/releases/download/app-payload-latest/manifest.json \
     | python3 -c "import sys,json;m=json.load(sys.stdin);print(m['run_date'], m['generated_at'])"
   ```
   `run_date` should equal **today** (or yesterday before the 01:00 Pi ingest / 03:00 Brisbane
   watchdog). If it's stale by >1 day, the daily publish is failing.

2. **Check the Pi** (SSH; see §4 for access):
   ```bash
   ssh ar-local-pi5 'systemctl is-active ar-local-daily.timer; \
     systemctl list-timers ar-local-daily.timer --no-pager | grep ar-local; \
     systemctl show ar-local-daily.service -p Result -p ExecMainStatus; \
     sudo test -f /etc/ar-local/app-payload.env && echo "token env: present" || echo "token env: MISSING"; \
     journalctl -u ar-local-daily.service -n 40 --no-pager | grep -i "app.payload\|publish\|GH_TOKEN" '
   ```

3. **Trigger a run manually** (it ingests + publishes if the token is present):
   ```bash
   ssh ar-local-pi5 'sudo systemctl start --no-block ar-local-daily.service'
   # watch: journalctl -u ar-local-daily.service -f   (Ctrl-C to stop)
   ```
   A full banks ingest takes ~10–40 min; the publish step is at the end.

4. **Publish path in code**: `pi_daily_sync.py` → `maybe_publish_app_payload()` (gated by
   `AR_LOCAL_APP_PAYLOAD` env) → `app_payload.build_and_publish(exports)`. Publishing is
   **token-gated and non-fatal** (a publish failure never fails the ingest). Journald:
   `journalctl -u ar-local-daily.service -n 80 --no-pager | grep -E 'app_payload|pi_daily_sync.*app_payload'`.

**Alerts on missed/failed ingest** (no manual checks):
- Pi (optional SMTP): `ar-local-daily.service` and `ar-local-daily-watchdog.service` use
  `OnFailure=ar-local-ingest-alert.service` → `pi_ingest_alert.py` (SMTP via
  `/etc/ar-local/notify.env`). Install: `sh deploy/pi/install-ingest-notify.sh` then
  `sh deploy/pi/install-pi-systemd.sh /srv/ar-local && sudo systemctl daemon-reload`.
  Operator setup: `/etc/ar-local/notify.env` (see `deploy/pi/notify.env.example`).
- GitHub (no SMTP secrets): `.github/workflows/pi-ingest-watchdog.yml` runs at **03:00
  Australia/Brisbane** daily (cron `0 16` + `0 17` UTC; hour gate keeps only the 03:00
  Brisbane run). Expects `app-payload-latest` manifest `run_date` = **today in Brisbane**
  (2h buffer after **01:00** Pi ingest — requires `deploy/pi/ar-local-daily.timer` at 01:00
  local, PR #195). On stale/missing: opens a deduped `ingest-missed` issue and
  **fails the workflow** so GitHub emails watchers who enable Actions notifications.
- **GitHub notification setup** (repo watcher): GitHub → Settings → Notifications → enable
  **Actions** and **Issues** for `yanniedog/AR-local` (same channel as other repo events; no
  workflow SMTP).
- Brisbane is UTC+10 year-round (no DST). `0 17 * * *` UTC = 03:00 Brisbane; `0 16 * * *`
  UTC hits 02:00 Brisbane and is skipped by the workflow gate.
- Test manifest check locally:
  `python3 scripts/pi_ingest_manifest_check.py --expected-tz Australia/Brisbane`
- Test Pi SMTP (dry-run): `python3 pi_ingest_alert.py --reason missed-ingest --dry-run`
- **CRLF dirty tree:** `pi_daily_sync.py` auto-discards line-ending-only changes; real edits
  still block ingest — run `git status` on the Pi and reset or commit intentionally.

**Common failure modes** (in order of likelihood):
- **Dirty Pi git tree.** `pi_daily_sync` refuses pull when tracked files differ (often CRLF on
  `app_payload.py` after Windows edits). Fix: `ssh ar-local-pi5 'cd /srv/ar-local/AR-local && git checkout -- .'`
  then `sudo systemctl start --no-block ar-local-daily.service`.
- **Pi offline.** Check `tailscale status` for `ar-local-pi5` (must be "active", not
  "offline"). If offline, nothing publishes — the user must power/reconnect it. The deploy
  Action can't reach it either.
- **PAT expired/revoked.** The token lives in `/etc/ar-local/app-payload.env`
  (`GH_TOKEN=github_pat_…`, fine-grained, repo `yanniedog/AR-local`, **Contents: R/W**).
  Re-install with `sudo sh /srv/ar-local/AR-local/deploy/pi/install-app-payload-token.sh <pat>`
  then `sh deploy/pi/install-pi-systemd.sh /srv/ar-local && sudo systemctl daemon-reload`.
- **`AR_LOCAL_APP_PAYLOAD` not set / unit not loading the env file.** Confirm
  `systemctl cat ar-local-daily.service | grep EnvironmentFile` shows
  `EnvironmentFile=-/etc/ar-local/app-payload.env`. If missing, run `install-pi-systemd.sh`.
- **Pi behind on code.** `ssh ar-local-pi5 'cd /srv/ar-local/AR-local && git log --oneline -1'`.
  It self-updates via `ar-local-deploy-watchdog.timer`, or force it:
  `ssh ar-local-pi5 'cd /srv/ar-local/AR-local && python3 pi_deploy_verify.py --deploy'`.

**Manual bootstrap (publish without waiting for the timer)** — build on the Pi, publish
from a machine that has `gh` auth (or with `GH_TOKEN` set):
```bash
ssh ar-local-pi5 'cd /srv/ar-local/AR-local && \
  latest=$(ls -d /srv/ar-local/data/runs/*/_exports | sort | tail -1) && \
  python3 app_payload.py build --exports "$latest" --out /tmp/ar-pay'
scp 'ar-local-pi5:/tmp/ar-pay/*' ./ar-pay/
python3 app_payload.py publish --dir ./ar-pay --require-token   # uses gh auth or GH_TOKEN
```

### Task B — "Make the app look & function like the web dashboard"

**Target to match:** open `http://100.78.28.10:8808/` (or `http://100.78.28.10/`) **in a
phone browser while on the Tailscale tailnet**, and compare side-by-side with the app.
The dashboard mirrors australianrates.com.

**Dashboard anatomy** (from `dashboard/index.html` + `dashboard/app.js`):
- **Segment nav**: Home loans / Savings / Term deposits (+ an Economic Data section that is
  out of scope for the app).
- **Hero "market intro" card**: run date (`#hero-run`), leader/best rate
  (`#hero-leader-label` / `#hero-leader`), metric rows (`#hero-rows`), and **lender logos**
  (`#selectedLogos`).
- **Workspace / chart block**: the **ribbon** distribution + the **hierarchical drill-down**
  ("report ribbon" tree), a chart toolbar with **focus presets** + a **sort toggle**
  (`#chart-toggle-sort`), and a **standard / non-standard account toggle**
  (`#chart-toggle-nonstandard`).
- **Light/dark theme**, JSON/XLSX export links (`#jsonLink` / `#xlsxLink`).

**Dashboard source files** (study these to replicate look/behaviour):
| File | What it does |
|---|---|
| `dashboard/index.html` | page structure / sections |
| `dashboard/app.js` | data fetch + render orchestration |
| `dashboard/app.css` | theme tokens (AR-local blue `#3b82f6`/`#60a5fa`), layout |
| `dashboard/hierarchy.js` | the drill-down "report ribbon" tree + tier ordering |
| `dashboard/cdr-ribbon-map.js`, `ar-ribbon-canonical-tiers.js` | ribbon tier labels/order |
| `dashboard/cdr-taxonomy-tree.js` | taxonomy → tree |
| `dashboard/chart.js` | ribbon/chart rendering |
| `dashboard/rba-cash-rate.js` | RBA cash-rate series |
| `dashboard/ar-bank-brand.js`, `local-brand.js` | lender brand colours/logos |
| `cdr_dashboard_server.py` | `BANK_SECTION_COLUMNS`, `aggregate_ribbon_rows`, API routes |

**App ↔ dashboard mapping** (where to edit on the app side):
| Dashboard feature | App equivalent | Status / gap |
|---|---|---|
| Segment nav (Loans/Savings/Deposits) | `app/(tabs)/index.tsx`, `app/(tabs)/browse.tsx` (`SegmentedControl`) | ✅ done |
| Hero run-date + best rate + metrics | `app/(tabs)/index.tsx` | ✅ done |
| Ribbon (min/median/mean/max + RBA marker) | `src/components/Ribbon.tsx` | ✅ done (SVG) |
| Drill-down hierarchy / report ribbon | `src/components/HierarchyView.tsx` + `src/data/taxonomy.ts` (driven by each row's `taxonomy_path`) | ✅ done |
| Product detail (terminal leaf) | `app/product/[key].tsx` (+ `details` payload) | ✅ done |
| RBA cash-rate chart | `src/components/charts.tsx`, shown on Home/Trends | ✅ done |
| **Lender logos** | `src/components/BankAvatar.tsx`; canonical PNGs embedded in release `core.brands` for offline rendering, with monogram fallback | ✅ done |
| **Standard / non-standard toggle** | persisted top-level toggle on Home/Browse; hierarchy drill-down and Search inherit it | ✅ done |
| Sort toggle / chart focus presets | Home ribbon presets open hierarchy-scoped `app/search.tsx` sort chips | ✅ done |
| Light/dark theme | `src/theme/` (`ThemeProvider`, `colors.ts`) | ✅ done |
| JSON/XLSX export | — | ❌ not applicable to mobile (skip) |
| Economic Data tab | — | ❌ out of scope |

**Important data note:** the app's drill-down is built from each rate row's
**`taxonomy_path`** (dot-delimited, e.g. `HOME_LOAN.OO.PI.VARIABLE.LVR_70_80`), which the Pi
emits and `app_payload.py` includes in the core payload. If you change the taxonomy on the
Pi side (`cdr_taxonomy.py`), keep `mobile/src/data/taxonomy.ts` label maps + ordering in
sync (see its tests in `mobile/__tests__/taxonomy.test.ts`). Edge cases already handled:
`LVR_UNSP` → "LVR n/a" (sorts last), `OVERDRAFT`/untyped rows excluded from the hierarchy
(still searchable), non-standard excluded by default, distinct **product** count vs rate-row
count.

### Task C — "The APK should auto-download the GitHub payload and render locally"

**This already works.** How:
- Config: `mobile/app.json` → `expo.extra` = `{ repo, releaseTag: "app-payload-latest",
  manifestUrl }`, read by `mobile/src/config.ts`.
- Fetch: `mobile/src/data/payload.ts` GETs the manifest, compares `run_date`/sha to the
  cached copy, downloads + gunzips `core` (then `details` in the background), verifies sha256.
- Persist: `mobile/src/data/cache.ts` writes an atomic single bundle to `expo-file-system`;
  `mobile/src/data/store.ts` (Zustand) hydrates the UI from cache first (offline-first),
  then refreshes.
- Bundled fallback: `mobile/src/data/sample.js` (real sample) shows instantly on first
  launch until the live download completes.

**To verify on a device**: install/run the app (see §3), confirm the Home header shows the
current `run_date`, then airplane-mode → relaunch → it still renders from cache.
**To verify the bytes**: `manifestUrl` → `core` URL should both return HTTP 200 publicly.

---

## 3. Build & run the app

```bash
cd mobile
npm install                 # .npmrc sets legacy-peer-deps (React 19)
npx expo start              # Expo Go (must be SDK 54); press a/i or scan QR
# or, with the EAS dev build installed on the device (notifications/background work):
npx expo start --dev-client
npx expo start --tunnel     # if phone and PC aren't on the same Wi-Fi
```
Checks: `npm run typecheck` (`tsc`), `npm run lint`, `npm test` (jest), `npx expo export`.

**EAS builds** (cloud, under `yannieyannies-team`):
```bash
npm i -g eas-cli
EXPO_TOKEN=<expo-access-token> eas build --profile development --platform android
# build status: EXPO_TOKEN=… eas build:view <id> --json   (NOTE: build:view has no --non-interactive flag)
```
Profiles are in `mobile/eas.json` (development = dev client + internal distribution).
The last Android dev build artifact:
`https://expo.dev/accounts/yannieyannies-team/projects/ar-local-rates/builds/9b2911bd-162a-4b47-a0a5-4407027583db`

### Mobile observability (Clarity + Crashlytics)

Forever-free stack: **Microsoft Clarity** (session replay) + **Firebase Crashlytics**
(crashes + bridged `debugLog` warn/error/info lines). Implemented in
`mobile/src/lib/observability.ts`; wired from `mobile/app/_layout.tsx` and Settings.

**Prerequisites**

| Requirement | Value / note |
|---|---|
| Installable build | **EAS or local dev client** — **not Expo Go** (native modules) |
| Android package | `com.eyex.australianrates` (`mobile/app.json` → `expo.android.package`) |
| iOS bundle ID | `com.eyex.australianrates` (`mobile/app.json` → `expo.ios.bundleIdentifier`) |
| Native SDK change | **Rebuild** after first Firebase/Clarity setup or config swap (preview/production profile) |
| EAS project | `@yannieyannies-team/ar-local-rates` — [expo.dev project](https://expo.dev/accounts/yannieyannies-team/projects/ar-local-rates) |
| Robot token | `EXPO_TOKEN` — see §7 / EAS builds above (`ar-local-eas` robot) |

**Part 1 — Microsoft Clarity**

1. [clarity.microsoft.com](https://clarity.microsoft.com/) → **New project** → **Mobile**.
2. Copy the **Project ID** (not the API key).
3. Set `EXPO_PUBLIC_CLARITY_PROJECT_ID`:
   - **EAS cloud builds (recommended):** expo.dev → `yannieyannies-team` / `ar-local-rates` →
     **Environment variables** → add for **preview** and **production** (and development if
     you want replay on dev-client release builds).
   - **Local `eas build` / export:** create `mobile/.env` (gitignored) with
     `EXPO_PUBLIC_CLARITY_PROJECT_ID=<id>` or export the var in the shell before building.
4. **Runtime behavior:**
   - Clarity **does not initialize when `__DEV__` is true** (Metro dev server / most local
     `expo start` sessions) even if the env var is set.
   - On non-`__DEV__` builds, Clarity starts only when **Settings → Diagnostics** is on
     (default **on**; persisted in `prefs.diagnosticsEnabled`).
   - Toggle **off** → `clarity.pause()`; toggle **on** → `clarity.resume()` or first init.

**Part 2 — Firebase Crashlytics**

1. [console.firebase.google.com](https://console.firebase.google.com/) → **Add project** (or
   reuse an existing one).
2. **Build** → **Crashlytics** → **Enable** (adds the SDK hooks EAS expects).
3. Register mobile apps in that Firebase project (Android now; iOS when you ship iOS):
   - **Android** — package `com.eyex.australianrates` → download `google-services.json`
   - **iOS** (optional for now) — bundle ID `com.eyex.australianrates` → download
     `GoogleService-Info.plist`
4. **Skip Firebase console Gradle/Kotlin steps 2–3** (google-services plugin, firebase-bom).
   This repo is **Expo managed prebuild**: `@react-native-firebase/app` and
   `@react-native-firebase/crashlytics` in `mobile/app.json` apply the native SDK at
   **`eas build` prebuild** — do not hand-edit `android/build.gradle.kts`.
5. Place the real files (gitignored — never commit):
   - `mobile/google-services.json`
   - `mobile/GoogleService-Info.plist`
6. Committed placeholders (safe to diff; used when real files absent):
   - `mobile/google-services.json.example`
   - `mobile/GoogleService-Info.plist.example`
7. `mobile/app.json` already points `expo.android.googleServicesFile` and
   `expo.ios.googleServicesFile` at those paths; `mobile/firebase.json` holds Crashlytics
   native config (no secrets).

**Part 3 — CI / EAS** (not Firebase console "Part 3")

Firebase's onboarding wizard labels native Gradle edits as steps 2–3; for Expo those are
**automatic at EAS prebuild**. HANDOFF **Part 3** here means **CI secrets and EAS build
workflow** — not manual Android project sync.

| Secret / env | Where | Purpose |
|---|---|---|
| `EXPO_TOKEN` | GitHub Actions → Settings → Secrets | EAS upload/auth (required) — §7 |
| `GOOGLE_SERVICES_JSON` | GitHub Actions secrets (optional) | Full `google-services.json` body; GHA materializes then uploads via `.easignore` |
| `GOOGLE_SERVICE_INFO_PLIST` | GitHub Actions secrets (optional) | Full `GoogleService-Info.plist` body; same upload path |
| `EXPO_PUBLIC_CLARITY_PROJECT_ID` | GitHub Actions secret **or** EAS project env | GHA runs `eas env:create` before build when secret set |
| `GOOGLE_SERVICES_JSON` (file) | EAS project env (expo.dev, optional) | Alternative: file-type env; path read by `eas-build-pre-install` hook |


**Android keystore after package / application ID change**

EAS stores the signing keystore **per Android application identifier** (`expo.android.package`).
Renaming the package (e.g. `com.yanniedog.arlocalrates` → `com.eyex.australianrates` in PR #183)
requires a **one-time** keystore for the new ID before **`mobile-eas-build`** or any
`eas build --non-interactive` CI job can succeed. Expo explicitly blocks auto-generation in
non-interactive mode (`Generating a new Keystore is not supported in --non-interactive mode`).

| Method | When to use |
|---|---|
| [expo.dev Credentials](https://expo.dev/accounts/yannieyannies-team/projects/ar-local-rates/credentials) → **Android** → `com.eyex.australianrates` → **Keystore** → **Generate new keystore** | Fastest; works with the `EXPO_TOKEN` robot after the keystore exists |
| Local interactive CLI | `cd mobile` then `EXPO_TOKEN=<token> npx eas-cli@16.14.1 credentials -p android` and choose **Set up a new keystore** (or reuse/upload an existing `.jks`) |
| One interactive cloud build | Same token, run `npx eas-cli@16.14.1 build -p android --profile preview` **without** `--non-interactive` once; EAS prompts to create the keystore |

After setup, re-run GitHub Actions → **mobile-eas-build** (preview / android). The workflow
also runs `credentials:configure-build` before upload to fail fast with this doc link.

**Note:** The old keystore for `com.yanniedog.arlocalrates` remains on Expo but does **not**
apply to the new package name; Play Store treats the new ID as a different app.


**Primary internal Android build (free, unlimited):** `.github/workflows/mobile-android-apk.yml`
— runs on `ubuntu-latest` (JDK 17, Android SDK): materialize Firebase → bump `versionCode`
from rolling `app-apk-latest` manifest → `expo prebuild` → `gradlew assembleRelease` → publish
`app-preview.apk` + `app-apk-latest.json` + **`app-preview-qr.png`** + **`install.html`** to GitHub
release tag **`app-apk-latest`**. Triggers:
`workflow_dispatch` and pushes to `main` under `mobile/**`. Signing: `ANDROID_KEYSTORE_B64`
secrets, or `EXPO_TOKEN` to pull the default EAS keystore (`materialize-android-keystore.mjs`).

**Optional EAS cloud build:** `.github/workflows/mobile-eas-build.yml` — `workflow_dispatch` only
(does not gate PR merges; subject to EAS quota). Inputs: `profile` (`development` / `preview` /
`production` from `mobile/eas.json`), `platform` (`android` / `ios` / `all`). Use when EAS
quota is available or for iOS.

Steps relevant to observability:
- **Materialize Firebase config (GHA)** — if `GOOGLE_SERVICES_JSON` is set, writes
  `mobile/google-services.json`; else runs `node scripts/ensure-firebase-config.mjs` (placeholder
  from `.example`). Same pattern for `GOOGLE_SERVICE_INFO_PLIST` / `GoogleService-Info.plist`.
- **`ensure-firebase-config.mjs`** — also runs as **`eas-build-pre-install`** on EAS cloud
  (before `npm install`). Fallback when Firebase files are missing: inline/path env from EAS file
  secrets, `*_B64` env, or copies `.example`. Primary GHA path: materialize locally then upload
  with `EAS_NO_VCS=1` + `mobile/.easignore` (`!google-services.json` whitelist).
- **Validate JS bundle** — `npm run typecheck` + platform `export:*` (each `preexport:*`
  also runs `ensure-firebase-config.mjs`).
- **EAS Build** — `EAS_NO_VCS=1` + `mobile/.easignore` uploads materialized Firebase files;
  optional `eas env:create` for `EXPO_PUBLIC_CLARITY_PROJECT_ID` from GH secret.

Trigger from GitHub: Actions → **mobile-eas-build** → Run workflow. Or locally:
```bash
cd mobile
EXPO_TOKEN=<token> eas build --profile preview --platform android
```

**In-app APK self-update (preview / internal distribution)**

Settings → **App update** (Android only): **Check for update** / **Download update** compares
`nativeApplicationVersion` + `nativeBuildVersion` against a rolling GitHub manifest and
installs a newer preview APK via the system package installer.

| Piece | Location / URL |
|---|---|
| Manifest URL (baked in) | `app.json` → `expo.extra.apkManifestUrl` → `…/app-apk-latest/app-apk-latest.json` |
| APK asset | Same release tag → `app-preview.apk` |
| Install QR (PNG) | Same release tag → `app-preview-qr.png` — encodes direct APK download URL (Android Chrome) |
| Install page | Same release tag → `install.html` — desktop-friendly QR + direct link |
| Client logic | `mobile/src/lib/appUpdateLogic.ts` (compare/fetch) + `appUpdate.ts` (download/install) |
| Publish script | `mobile/scripts/publish-apk-manifest.mjs` (`--apk` GHA; `--eas-build-id` EAS; `--qr-only` refresh QR without rebuild) |
| Version bump (GHA) | `mobile/scripts/bump-android-version-code.mjs` — monotonic `versionCode` from manifest |

After a successful **mobile-android-apk** run (or **mobile-eas-build** preview/android), both
files land on GitHub release tag **`app-apk-latest`**. First build seeds the release;
subsequent builds clobber the rolling assets. Both **mobile-android-apk** and **mobile-eas-build** (preview/android) run
`bump-android-version-code.mjs` against the published manifest so version codes stay monotonic
across either publisher (`appVersionSource: local`, no preview `autoIncrement`).

Operator: run **mobile-android-apk** on `main` once to seed the release, then devices with an
older preview build can update from Settings without reinstalling from expo.dev.

**Scan-to-install QR (EAS-style, no expo.dev link)**

| Where | How |
|---|---|
| GitHub release assets | [app-apk-latest](https://github.com/yanniedog/AR-local/releases/tag/app-apk-latest) → **`app-preview-qr.png`** or open **`install.html`** on desktop |
| GHA job summary | **mobile-android-apk** (and **mobile-eas-build** preview/android) append markdown with `![Install QR](…)` linking to the release PNG |
| QR payload | Direct APK URL: `…/releases/download/app-apk-latest/app-preview.apk` — scan with **Android Chrome**; allow “Install unknown apps” when prompted |
| Refresh QR only (APK unchanged) | `cd mobile` → `GH_TOKEN=… node scripts/publish-apk-manifest.mjs --qr-only --repo yanniedog/AR-local` |

**Part 4 — Verification**

| Check | How |
|---|---|
| Crashlytics logs | Install a **preview/production** build with real Firebase config + Diagnostics **on** → use the app → Firebase console → Crashlytics → **Logs**. `debugLog` **info/warn/error** lines appear via `bridgeLogToCrashlytics` (`mobile/src/lib/debugLog.ts`); **debug** level is local-only. **error** also calls `recordError`. |
| Crashlytics crashes | Force a test crash or wait for a real native crash; same console → **Issues**. |
| Clarity replay | Non-`__DEV__` build + `EXPO_PUBLIC_CLARITY_PROJECT_ID` set + Diagnostics **on** → browse a few screens → clarity.microsoft.com → project → **Recordings** (may lag a few minutes). |
| Diagnostics toggle | Settings → **Diagnostics & crash reporting** — off stops new Clarity capture and Crashlytics collection; on resumes. Local **Debug log** viewer/upload (`/debug-log`) is independent. |
| Placeholder detection | If CI log shows `ensure-firebase-config: copied …example → …` and no Crashlytics data, add real Firebase files or GitHub secrets. |

**Operator checklist**

- [ ] EAS **preview** or **production** build installed on device (not Expo Go)
- [ ] `EXPO_PUBLIC_CLARITY_PROJECT_ID` in GH secret, EAS env, or `mobile/.env` for local EAS CLI
- [ ] Real `google-services.json` + `GoogleService-Info.plist` (or GH secrets for workflow builds)
- [ ] Crashlytics **enabled** in Firebase console for the project
- [ ] Rebuilt **after** adding native config / env vars
- [ ] Settings → Diagnostics **on** for the test session
- [ ] Confirmed data in Firebase Crashlytics + Clarity dashboards

**Common mistakes**

| Mistake | Symptom | Fix |
|---|---|---|
| Testing in Expo Go | No native modules; observability silently no-ops | Install EAS dev/preview APK or dev client |
| Only `mobile/.env` for Clarity, not EAS/GHA env | Cloud builds missing Project ID; no recordings | Set GH secret or expo.dev project env |
| Placeholder Firebase files | Build/export green; zero Crashlytics events | Drop real JSON/plist from Firebase console or set GH secrets |
| Expecting Clarity in `expo start` / `__DEV__` | No recordings despite correct Project ID | Use preview/production build (`__DEV__` false) |
| Diagnostics toggle off | No new logs or replays | Enable in Settings (default is on for fresh installs) |
| Wrong Firebase app package/bundle | Crashlytics dashboard empty | Re-register apps as `com.eyex.australianrates` |
| Forgot rebuild after first SDK setup | Old binary without Crashlytics/Clarity native code | `eas build` or **mobile-eas-build** workflow |
| `debug` lines missing in Crashlytics | By design | Only info/warn/error bridge; use Settings → Debug log locally |

---

## 4. The Pi (data source) — access & layout

- **SSH**: `ssh ar-local-pi5` (configured in `~/.ssh/config` → HostName `100.78.28.10`,
  user `pi`, **Tailscale**). Needs the tailnet up on your machine (`tailscale status`).
- **Repo on Pi**: `/srv/ar-local/AR-local` (self-updates via `ar-local-deploy-watchdog.timer`).
- **Data on Pi**: `/srv/ar-local/data/runs/<date>/_exports/` (has
  `dashboard-cache/<date>/banks.json` + `latest.json`, which `app_payload.py` reads).
- **Dashboard**: `http://100.78.28.10:8808/` (backend) and `http://100.78.28.10/` (nginx :80).
- **Daily**: `ar-local-daily.timer` → `ar-local-daily.service` (runs as user `pi`) →
  `pi_daily_sync.py --banks-only`, **01:00 local (`Australia/Hobart`)** — Pi `timedatectl` timezone.
- **systemd units** live in `deploy/pi/*.service|*.timer`; render/install with
  `sh deploy/pi/install-pi-systemd.sh /srv/ar-local && sudo systemctl daemon-reload`.
- Passwordless `sudo` for the needed commands is configured (`deploy/pi/install-pi-sudoers.sh`).

---

## 5. The payload contract (`app_payload.py`, `schema_version: 1`)

`python3 app_payload.py build --exports <_exports dir> --out <dir>` →
- **`manifest.json`** (small, polled first): `run_date`, `generated_at`, `counts`,
  `schedule`, and `files.{core,details}` each with `name`, `bytes`, `sha256`, `url`.
- **`core-<date>-<sha12>.json.gz`**: `{ run_date, sections:{Mortgage,Savings,TD:{rates[],
  ribbon}}, brands, rba[] }`. Each rate row carries `taxonomy_path` (drives the app tree).
- **`details-<date>-<sha12>.json.gz`**: per-`product_key` fees/features/eligibility/
  constraints for the detail screen.

**Release model (per-date + rolling latest):**

| Tag | Purpose | Assets |
|-----|---------|--------|
| `app-payload-latest` | Mobile app polls this for the newest `run_date` | Rolling manifest + ~20 recent core/details (pruned) |
| `app-payload-YYYY-MM-DD` | Immutable snapshot for that ingest date | Exactly 3 assets (manifest + core + details); never pruned |

`pi_daily_sync` → `build_and_publish_dual()` publishes **both**: dated tag for the ingest
`run_date`, then updates `app-payload-latest` when `run_date` is not older than the live
rolling manifest.

`python3 app_payload.py --tag app-payload-2026-06-08 publish --dir <dir> [--require-token]`
→ uploads via `gh` (auth via `GH_TOKEN`/`GITHUB_TOKEN` env **or** `gh` login). Content-addressed
asset names; manifest uploaded last. Rolling tag refuses to downgrade to an older `run_date`
unless `--force`. Dated tags are independent snapshots. Journald:
`[app_payload] publish starting|succeeded|failed`, `[app_payload] dated publish finished`,
`[pi_daily_sync] app_payload publish`.

**Backfill historical dates** (Pi — one dated release per ingested folder, then refresh latest):

```bash
ssh ar-local-pi5 'cd /srv/ar-local/AR-local && sudo bash scripts/backfill-app-payload.sh'
# optional bounds: --from-date 2026-05-13 --to-date 2026-06-08
# preview: --dry-run ; re-upload existing: --force
```

CI: `.github/workflows/app-payload-publish.yml` (manual `workflow_dispatch` re-publish from
the committed sample); the **Pi is the primary daily publisher**.

---

## 6. Dev workflow (branches, PR gates, merge)

- **Branch off `main`, open a PR.** `main` is protected — direct pushes are blocked. Note:
  `main` is checked out in another git **worktree** locally (`AR-local-banking-only-pi-ssd`),
  so work from a feature branch and don't `git checkout main` here.
- **Required status checks (branch protection):** `bot-feedback-gate` + `bot-presence-gate`,
  `strict: true` (up-to-date), `enforce_admins: true` (**admins cannot bypass** — even
  `gh pr merge --admin` is refused).
- **Required bot (presence gate):** **gemini** only (`AR_BOT_WAIT_REQUIRED=gemini` in
  `pr-bot-presence-gate.yml`). Sourcery is optional — it may still comment but does not block
  merge. A bot's `pull_request_review` event auto-re-runs the presence gate.
- **Resolving a thread emits no webhook** → a previously-failed gate won't auto-re-run after
  a resolve-only round. To re-fire: push a commit, post an inline reply, or
  `gh run rerun <run-id>`. Multiple same-named gate runs on one commit can leave branch
  protection latched on an old failure — a **fresh push (new head)** is the reliable fix.
- **Enable auto-merge**: `gh pr merge <n> --squash --auto`. It lands when all required checks
  are green and **0 review threads are unresolved**.
- **Address bot threads in-thread**: reply, then resolve via GraphQL `resolveReviewThread`.
  Read each thread before resolving; don't auto-resolve unread threads.
- Commit trailer used here: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`
  (adjust for your agent). PR body trailer: `🤖 Generated with [Claude Code](…)`.

---

## 7. Secrets & credentials (values NOT in this doc)

| Secret | Where it lives | Purpose | Rotate |
|---|---|---|---|
| GitHub fine-grained PAT | `/etc/ar-local/app-payload.env` on the Pi (`0600`, root) | Pi → GitHub Release upload (daily publish) | GitHub → Settings → Developer settings → Fine-grained tokens; re-install via `install-app-payload-token.sh` |
| Expo robot access token | `ar-local-eas` robot under `yannieyannies-team` | `eas build` / project mgmt | expo.dev → account → Access tokens (delete/recreate) |
| `PI_SSH_PRIVATE_KEY`, `PI_SSH_HOST`, `PI_SSH_USER` | repo Actions secrets | GitHub → Pi deploy | repo Settings → Secrets |
| `TS_OAUTH_CLIENT_ID/SECRET` | **not set** | Would let GitHub-hosted runners reach the Tailscale Pi (deploy + a future Actions-driven publish). Without it, the Pi self-deploys via its on-box watchdog | Tailscale admin → OAuth clients |

Tokens pasted into chat during setup should be **rotated** at the user's convenience. The Pi
needs its PAT to keep publishing — don't revoke that without re-installing a new one.

---

## 8. Gotchas

- **Pi offline = everything stops.** Check `tailscale status` first when data looks stale.
- **`enforce_admins: true`** — you cannot force-merge; satisfy the gates for real.
- **`bot-presence-gate` is single-shot** and waits for **gemini** only. If the gate failed
  before gemini reviewed, re-run it with a fresh push or `gh run rerun <run-id>` once gemini
  has commented.
- **Pi file ownership**: some `/srv/ar-local` paths are root-owned; use the blessed scripts
  (`pi_deploy_verify.py`, `install-pi-systemd.sh`) rather than ad-hoc `git pull`/edits.
- **Line endings**: repo is LF; Windows checkouts warn about CRLF — harmless.
- **`eas build:view`** does **not** accept `--non-interactive` (it errors). Use just `--json`.
- **Taxonomy sync**: changing `cdr_taxonomy.py` (Pi) without updating
  `mobile/src/data/taxonomy.ts` labels/order will show raw codes / mis-sorted tiers.
- **projectmem**: this repo uses a `projectmem` MCP server (see `CLAUDE.md`); Claude agents
  must call `get_instructions`/`get_summary` first and log via its tools. Non-Claude agents
  without that MCP can read `.projectmem/summary.md` (human-readable, auto-generated) but
  should **not** hand-edit `.projectmem/` files.

---

## 9. Quotas & costs (pipeline audit, condensed)

Normal ops are **$0**. Billable or capped components:

| Component | Limit | Overage / reset | AR-local usage |
|---|---|---|---|
| **EAS cloud builds** (Free plan) | **15 Android + 15 iOS / month** | No pay-as-you-go on Free; upgrade or wait for **1st-of-month** reset | **`mobile-eas-build`** only; quota exhausted Jun 2026 — use **`mobile-android-apk`** instead |
| **GHA Gradle APK** (`mobile-android-apk`) | Unlimited on **public** repo | — | **Primary** internal Android preview path (no EAS quota) |
| **GitHub Actions** (other workflows) | Public repo: generous minutes | Private repos: 2000 min/mo Free | Pi deploy, ingest watchdog, PR gates |
| **GitHub Releases** | Asset size limits per file/release | — | `app-payload-latest`, `app-apk-latest`, dated payload tags |
| **Firebase Crashlytics** (Spark) | Free tier | Blaze metered if enabled | Preview/production builds with real `google-services.json` |
| **Microsoft Clarity** | Free, no session cap | — | Non-`__DEV__` builds + Diagnostics on |
| **paste.rs** (debug log upload) | Public, unauthenticated | No SLA | Settings → Debug log → Upload |
| **Tailscale** (Pi access) | Personal plan | — | `100.78.28.10` dashboard + SSH |
| **Pi self-host** | Local SSD / bandwidth | — | Daily ingest + dashboard; no cloud VM bill |

**Rule of thumb:** Android preview APKs → **`mobile-android-apk`** (free). Reserve EAS cloud for
iOS or when you need Expo's managed build queue. Store fees (Apple/Google) apply only at
public-store submission — not used yet.

---

## 10. Command cheat-sheet

```bash
# Is the daily upload fresh?
curl -fsSL https://github.com/yanniedog/AR-local/releases/download/app-payload-latest/manifest.json | python3 -m json.tool | grep run_date

# Pi reachable?           tailscale status | grep ar-local-pi5
# Pi code / data:         ssh ar-local-pi5 'cd /srv/ar-local/AR-local && git log --oneline -1; ls -d /srv/ar-local/data/runs/*/ | tail -1'
# Trigger an ingest:      ssh ar-local-pi5 'sudo systemctl start --no-block ar-local-daily.service'
# Force-deploy latest:    ssh ar-local-pi5 'cd /srv/ar-local/AR-local && python3 pi_deploy_verify.py --deploy'

# App locally:            cd mobile && npm install && npx expo start
# App checks:             cd mobile && npm run typecheck && npm run lint && npm test && npx expo export

# Compare to dashboard:   open http://100.78.28.10:8808/ on a phone (on the tailnet)
```

---

## 11. Key files index

```
app_payload.py                         # build + publish the payload (Pi side)
pi_daily_sync.py                       # daily ingest; calls maybe_publish_app_payload()
cdr_dashboard_server.py                # web dashboard server (BANK_SECTION_COLUMNS, ribbon, APIs)
dashboard/                             # the web dashboard the app should resemble (see §2 Task B)
deploy/pi/                             # systemd units + install scripts (token, systemd, sudoers)
docs/MOBILE_APP.md                     # payload contract, Pi token setup, device testing/builds
docs/HANDOFF.md                        # this file

mobile/app.json                        # expo config: extra.{repo,releaseTag,manifestUrl}, eas.projectId
mobile/eas.json                        # EAS build profiles
mobile/src/config.ts                   # reads expo.extra (release/manifest config)
mobile/src/data/payload.ts             # fetch manifest → core/details (gunzip + sha256)
mobile/src/data/cache.ts               # atomic on-device cache (expo-file-system)
mobile/src/data/store.ts               # Zustand store; bootstrap (offline-first) + refresh
mobile/src/data/notifications.ts       # background refresh + local notifications
mobile/src/data/selectors.ts           # sort/filter/search/compare/best-rate
mobile/src/data/taxonomy.ts            # taxonomy_path → drill-down tree (+ tests)
mobile/src/components/Ribbon.tsx        # rate-distribution ribbon (SVG)
mobile/src/components/HierarchyView.tsx # the drill-down (ribbon + child categories / leaf products)
mobile/src/components/BankAvatar.tsx    # embedded lender logos with monogram fallback
mobile/app/(tabs)/index.tsx             # Home dashboard (hero + ribbon + categories + best)
mobile/app/(tabs)/browse.tsx            # hierarchy explorer (root)
mobile/app/node.tsx                     # one drill level (pushed per category)
mobile/app/search.tsx                   # flat search/sort/filter/compare (scoped to a node)
mobile/app/product/[key].tsx            # product detail (terminal leaf)
mobile/src/lib/debugLog.ts              # in-app ring-buffer logger (512KB / 2000 lines)
mobile/src/lib/observability.ts       # Clarity init + Crashlytics bridge + diagnostics toggle
mobile/app/debug-log.tsx                # Settings → view/share/upload logs (paste.rs POST)
mobile/.easignore                       # EAS upload rules; whitelists materialized Firebase JSON/plist
mobile/scripts/ensure-firebase-config.mjs  # copy .example Firebase configs when gitignored files absent
mobile/google-services.json.example     # Firebase Android placeholder (copy to gitignored path)
mobile/GoogleService-Info.plist.example # Firebase iOS placeholder
mobile/firebase.json                    # Crashlytics native config (no secrets)
mobile/src/lib/appUpdateLogic.ts       # in-app update: manifest fetch + version compare
mobile/src/lib/appUpdate.ts            # in-app update: APK download + system installer
mobile/src/lib/versionCompare.ts       # semver / versionCode compare helper
mobile/scripts/publish-apk-manifest.mjs # publish app-preview.apk + manifest + QR + install.html to GH release
mobile/scripts/bump-android-version-code.mjs  # monotonic versionCode from rolling manifest
mobile/scripts/materialize-android-keystore.mjs  # EAS keystore fetch or B64 secret for GHA signing
.github/workflows/mobile-android-apk.yml # primary free Android preview APK (GHA Gradle, no EAS quota)
.github/workflows/mobile-eas-build.yml # optional workflow_dispatch EAS cloud builds (quota-limited)
```

**Debug logs (mobile):** Settings → Debug log. Uploading logs posts plain text to `https://paste.rs/` (a public, unauthenticated service). The app shows an explicit confirmation dialog with a prominent warning about public visibility before uploading (`Upload to paste.rs?` — destructive Upload). The response body is the paste URL (e.g. `https://paste.rs/<id>`). Fetch with `curl https://paste.rs/<id>`. Warn/error/info lines also forward to Crashlytics when Diagnostics is on (see §3 observability).
