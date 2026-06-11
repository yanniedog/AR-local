import { GOOGLE_WEB_CLIENT_ID } from '../config';
import { debugLog } from './debugLog';

/**
 * Google sign-in via Firebase Auth (Phase C of docs/SECURITY_CDR_PIPELINE.md).
 *
 * Native modules are require()d lazily so builds/dev-clients that predate them
 * (and jest) never crash on import; every entry point degrades to a clear error.
 * Sign-in is enabled by setting `extra.googleWebClientId` in app.json to the
 * Web client ID from the Firebase console (Authentication → Google provider).
 */

export interface AuthUser {
  uid: string;
  email: string | null;
  displayName: string | null;
  photoURL: string | null;
}

export function isSignInConfigured(): boolean {
  return GOOGLE_WEB_CLIENT_ID.length > 0;
}

/* eslint-disable @typescript-eslint/no-require-imports -- lazy native modules */
function firebaseAuth(): typeof import('@react-native-firebase/auth') {
  return require('@react-native-firebase/auth');
}

function googleSignin(): typeof import('@react-native-google-signin/google-signin') {
  return require('@react-native-google-signin/google-signin');
}
/* eslint-enable @typescript-eslint/no-require-imports */

function toAuthUser(u: {
  uid: string;
  email: string | null;
  displayName: string | null;
  photoURL: string | null;
} | null): AuthUser | null {
  if (!u) return null;
  return { uid: u.uid, email: u.email, displayName: u.displayName, photoURL: u.photoURL };
}

let googleConfigured = false;

export async function signInWithGoogle(): Promise<AuthUser> {
  if (!isSignInConfigured()) {
    throw new Error('Google sign-in is not configured for this build yet');
  }
  const { GoogleSignin } = googleSignin();
  if (!googleConfigured) {
    GoogleSignin.configure({ webClientId: GOOGLE_WEB_CLIENT_ID });
    googleConfigured = true;
  }
  await GoogleSignin.hasPlayServices({ showPlayServicesUpdateDialog: true });
  const result = await GoogleSignin.signIn();
  const idToken = result.data?.idToken;
  if (!idToken) {
    throw new Error('Google sign-in was cancelled or returned no token');
  }
  const { getAuth, GoogleAuthProvider, signInWithCredential } = firebaseAuth();
  const credential = await signInWithCredential(
    getAuth(),
    GoogleAuthProvider.credential(idToken),
  );
  const user = toAuthUser(credential.user);
  if (!user) throw new Error('Firebase returned no user');
  debugLog.info('auth', `signed in uid=${user.uid}`);
  return user;
}

export async function signOutUser(): Promise<void> {
  const { getAuth, signOut } = firebaseAuth();
  await signOut(getAuth());
  try {
    const { GoogleSignin } = googleSignin();
    await GoogleSignin.signOut();
  } catch {
    // Google session cleanup is best-effort; Firebase sign-out already succeeded.
  }
  debugLog.info('auth', 'signed out');
}

/** Subscribe to auth state; returns unsubscribe. Safe when native auth is absent. */
export function subscribeAuth(cb: (user: AuthUser | null) => void): () => void {
  try {
    const { getAuth, onAuthStateChanged } = firebaseAuth();
    return onAuthStateChanged(getAuth(), (u) => cb(toAuthUser(u)));
  } catch (err) {
    debugLog.warn('auth', `auth unavailable: ${String((err as Error)?.message ?? err)}`);
    cb(null);
    return () => {};
  }
}
