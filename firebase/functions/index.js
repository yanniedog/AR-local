// issueContentKeys — Phase D of docs/SECURITY_CDR_PIPELINE.md.
// Returns the payload decryption key(s) a signed-in user's tier allows.
// Deploy steps: firebase/README.md.
import { initializeApp } from 'firebase-admin/app';
import { getFirestore } from 'firebase-admin/firestore';
import { defineSecret } from 'firebase-functions/params';
import { HttpsError, onCall } from 'firebase-functions/v2/https';

import {
  evaluateRateLimit,
  isValidKeyHex,
  keyId,
  resolveTier,
  scopesForTier,
} from './core.js';

// Same key as /etc/ar-local/payload.key on the Pi:
//   firebase functions:secrets:set PAYLOAD_KEY_FULL
const PAYLOAD_KEY_FULL = defineSecret('PAYLOAD_KEY_FULL');

initializeApp();

export const issueContentKeys = onCall(
  { region: 'australia-southeast1', secrets: [PAYLOAD_KEY_FULL] },
  async (request) => {
    if (!request.auth) {
      throw new HttpsError('unauthenticated', 'Sign in to request content keys');
    }
    const { uid } = request.auth;

    const ref = getFirestore().collection('keyIssuance').doc(uid);
    const allowed = await getFirestore().runTransaction(async (tx) => {
      const snap = await tx.get(ref);
      const next = evaluateRateLimit(snap.exists ? snap.data() : null, Date.now());
      if (!next) return false;
      tx.set(ref, next);
      return true;
    });
    if (!allowed) {
      throw new HttpsError('resource-exhausted', 'Daily key-issuance limit reached');
    }

    const keyHex = PAYLOAD_KEY_FULL.value().trim();
    if (!isValidKeyHex(keyHex)) {
      throw new HttpsError('failed-precondition', 'Content key is not configured');
    }

    const tier = resolveTier(request.auth.token);
    // Until windowed assets ship, every scope is served by the full key.
    const keys = scopesForTier(tier).map((scope) => ({
      scope,
      alg: 'aes-256-gcm',
      key_id: keyId(keyHex),
      key_hex: keyHex,
    }));
    return { tier, keys };
  },
);
