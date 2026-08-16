# CDR pipeline encryption + tiered auth — architecture

Status: **approved direction, phased rollout pending** (2026-06-11).
Owner request: encrypt CDR data end-to-end Pi → GitHub → app; auth (Google +
biometrics) decides how much history decrypts; everyone gets full access until
payments exist; make scraping/extraction hard even for paying users.

## Current state

- Pi → GitHub and app → GitHub already run over HTTPS (TLS), so *transport* is
  encrypted today. The gap is **at rest on the public GitHub Release**: anyone
  can download `app-payload-latest` assets and read the full CDR dataset.
- The app has no accounts. `rateIntelligencePro` is a local stub pref.
  Firebase (Crashlytics) is already integrated on the app side.

## Constraint to be honest about

With no backend, any key the app can use offline is extractable from the APK.
Client-side gating is **obfuscation, not security**. Real tier enforcement
needs a small key service. We use Firebase (already a dependency) rather than
standing up new infrastructure; the Pi stays non-public.

## Target design

### 1. Payload encryption (Pi side, `app_payload*.py`)

- Encrypt every CDR-bearing asset (core, details, history, search,
  bank-history) with **AES-256-GCM** before upload. Manifest stays plaintext
  (no CDR data: hashes, sizes, key ids, `enc: aes-256-gcm`).
- Assets are already split by scope; additionally split history by **time
  window** (e.g. `current` = run day, `recent-30d`, `full`). Each window gets
  its own content-encryption key (CEK), rotated per release epoch.
- CEKs live on the Pi (mode 600, root-owned, like GH_TOKEN) and are wrapped
  per **tier key**: `tier-current`, `tier-full`. Tiering later becomes a key
  issuance change, not a payload format change.

### 2. Auth + key service (Firebase)

- **Firebase Auth** with Google provider (Apple Sign-In later for iOS review
  compliance). App flow: sign in → ID token → callable **Cloud Function**
  `issueContentKeys` → returns wrapped CEKs the user's tier allows.
- Tier from **custom claims** (`tier: free|pro`). Until payments exist, the
  function grants every authenticated user `tier-full` (owner decision).
  Later: free = `tier-current` (today ± N days), paid = `tier-full`.
- Function rate-limits key issuance per account and logs anomalies (one
  account fanning keys to many IPs = scraper signal).

### 3. Biometric unlock (app)

- `expo-local-authentication` (fingerprint / Face ID) + `expo-secure-store`
  with `requireAuthentication: true`: content keys and the Firebase session
  are stored hardware-backed and only released after a biometric prompt.
- Offline grace: keys cached in SecureStore keep working without network;
  biometric prompt still gates access on app start.

### 4. Anti-scraping / extraction friction

- Public GitHub Release exposes ciphertext only — casual scraping dies here.
- Keys held in memory after biometric release; never written to plain
  AsyncStorage; no bulk export UI; FileSystem cache stores ciphertext and
  decrypts on read.
- Hermes bytecode + ProGuard/R8 on Android builds; optional Play Integrity
  attestation in `issueContentKeys` later.
- Accepted residual risk: a determined paying user can screen-scrape what
  they can see. The goal is friction + audit, not impossibility.

## Phases (each its own PR)

| Phase | Scope | Notes |
| --- | --- | --- |
| A | Pi: AES-256-GCM encrypt assets, manifest key ids (`payload_crypto.py`; gated by `AR_LOCAL_PAYLOAD_ENC`, OFF until Phase B ships; key via `deploy/pi/install-payload-enc-key.sh`; windowed history split moves to Phase B) | **implemented, flag off** |
| B | App: decrypt pipeline in payload fetch (`mobile/src/lib/payloadCrypto.ts`, auto-detects `ARE1` assets in `downloadInflate`); interim key via `app.json` extra `payloadDecKeyHex` (unset by default) | **implemented, dormant**; interim = obfuscation only; windowed history split deferred to Phase D where tiering needs it |
| C | Firebase Auth Google sign-in (`mobile/src/lib/auth.ts`, enabled by `extra.googleWebClientId` — owner must enable the Google provider in the Firebase console and paste the Web client ID); biometric app lock (`appLock.ts` + `AppLockGate`, pref `appLockEnabled`); SecureStore key custody (`keyVault.ts`, AFTER_FIRST_UNLOCK so background refresh keeps working) | **implemented**; sign-in dormant until `googleWebClientId` is set |
| D | `issueContentKeys` callable (`firebase/functions/`, secret `PAYLOAD_KEY_FULL`, per-uid 20/day rate limit, custom-claims tiers with `ENFORCE_TIERS=false`) + app client (`mobile/src/lib/keyService.ts` → SecureStore vault), synced on app start/sign-in; deploy runbook `firebase/README.md` | **implemented**; dormant until owner deploys the function and sets `extra.keyServiceUrl` |
| E | Hardening: rotation, rate limits, Play Integrity, scraper telemetry | post-payments |

## Open items

- Payments provider choice (Play Billing IAP vs Stripe) drives how claims get
  set — deferred until owner sets up payment systems.
- Key rotation cadence (proposal: weekly epoch keys, tier keys quarterly).
- iOS release timing (Apple Sign-In requirement).
