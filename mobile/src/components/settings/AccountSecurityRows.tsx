import React, { useEffect, useState } from 'react';
import { Alert } from 'react-native';

import { Button, AppText, Divider } from '../ui';
import { authenticateBiometric, biometricsAvailable } from '../../lib/appLock';
import {
  isSignInConfigured,
  signInWithGoogle,
  signOutUser,
  subscribeAuth,
  type AuthUser,
} from '../../lib/auth';
import { adoptConfigKey } from '../../lib/keyVault';
import { InfoRow, ToggleRow } from './settingsUi';

export function AccountSecurityRows({
  appLockEnabled,
  onAppLockChange,
}: {
  appLockEnabled: boolean;
  onAppLockChange: (v: boolean) => void;
}) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => subscribeAuth(setUser), []);

  const handleSignIn = async () => {
    setBusy(true);
    try {
      await signInWithGoogle();
      await adoptConfigKey();
    } catch (err) {
      Alert.alert('Sign-in failed', String((err as Error)?.message ?? err));
    } finally {
      setBusy(false);
    }
  };

  const handleSignOut = async () => {
    setBusy(true);
    try {
      await signOutUser();
    } catch (err) {
      Alert.alert('Sign-out failed', String((err as Error)?.message ?? err));
    } finally {
      setBusy(false);
    }
  };

  const handleAppLockChange = async (next: boolean) => {
    if (next && !(await biometricsAvailable())) {
      Alert.alert(
        'No screen lock set up',
        'Add a fingerprint, face unlock, or device PIN in your system settings first.',
      );
      return;
    }
    if (await authenticateBiometric(next ? 'Confirm to enable app lock' : 'Confirm to disable app lock')) {
      onAppLockChange(next);
    }
  };

  return (
    <>
      {user ? (
        <>
          <InfoRow label="Signed in as" value={user.email ?? user.displayName ?? user.uid} />
          <Button title="Sign out" variant="ghost" onPress={handleSignOut} loading={busy} disabled={busy} />
        </>
      ) : isSignInConfigured() ? (
        <>
          <AppText variant="tiny" color="textFaint" style={{ marginBottom: 8, lineHeight: 16 }}>
            Sign in to keep your rate history access when tiered plans launch.
          </AppText>
          <Button title="Sign in with Google" icon="logo-google" onPress={handleSignIn} loading={busy} disabled={busy} />
        </>
      ) : (
        <AppText variant="tiny" color="textFaint" style={{ lineHeight: 16 }}>
          Account sign-in is not enabled for this build yet.
        </AppText>
      )}
      <Divider style={{ marginVertical: 8 }} />
      <ToggleRow
        icon="finger-print"
        label="App lock"
        sub="Require fingerprint / face unlock on app start"
        value={appLockEnabled}
        onChange={(v) => void handleAppLockChange(v)}
      />
    </>
  );
}
