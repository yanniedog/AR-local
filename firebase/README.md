# Firebase key service (Phase D)

`functions/` holds the `issueContentKeys` callable: signed-in users receive the
payload decryption key(s) their tier allows (see
[docs/SECURITY_CDR_PIPELINE.md](../docs/SECURITY_CDR_PIPELINE.md)). Until
payments exist, every authenticated user gets the `full` tier
(`ENFORCE_TIERS = false` in `functions/core.js`).

## Owner deploy runbook (one-time)

Prereqs: the existing Firebase project (the one behind the real
`google-services.json`), upgraded to the Blaze plan; Firestore enabled;
`npm i -g firebase-tools` and `firebase login`.

```sh
cd firebase
firebase use <project-id>
# Same key the Pi uses (deploy/pi/install-payload-enc-key.sh):
firebase functions:secrets:set PAYLOAD_KEY_FULL   # paste the 64-hex key
cd functions && npm install && npm test && cd ..
firebase deploy --only functions
```

Then point the app at it in `mobile/app.json`:

```json
"extra": { "keyServiceUrl": "https://australia-southeast1-<project-id>.cloudfunctions.net/issueContentKeys" }
```

## Behaviour

- Unauthenticated calls → `unauthenticated`.
- Per-user fixed-window rate limit (20/day, Firestore `keyIssuance/<uid>`) →
  `resource-exhausted`; one account fanning keys out is the scraper signal to
  watch in logs.
- Tier from custom claims (`tier: full|free`) once `ENFORCE_TIERS` flips;
  free will then receive only the `current` scope when windowed assets ship.
- Response: `{ tier, keys: [{ scope, alg, key_id, key_hex }] }`. The app stores
  the key in SecureStore (`mobile/src/lib/keyService.ts` → `keyVault.ts`).

## Tests

`cd functions && npm test` — pure logic (`core.js`): tier/scope resolution,
rate-limit window, and the cross-language `key_id` vector shared with
`payload_crypto.py` and `payloadCrypto.ts`.
