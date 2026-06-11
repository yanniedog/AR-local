import { Ionicons } from '@expo/vector-icons';
import React, { useCallback, useEffect, useState } from 'react';
import { View } from 'react-native';

import { useStore } from '../data/store';
import { authenticateBiometric } from '../lib/appLock';
import { useTheme } from '../theme/ThemeProvider';
import { AppText, Button } from './ui';

/**
 * Cold-start biometric gate (Phase C). Children render only after the OS
 * prompt succeeds; the prompt falls back to device PIN/pattern, so this can't
 * permanently lock anyone out. Disabled (pass-through) until prefs hydrate so
 * the splash flow is unaffected for users without the lock.
 */
export function AppLockGate({ children }: { children: React.ReactNode }) {
  const theme = useTheme();
  const hydrated = useStore((s) => s.hydrated);
  const enabled = useStore((s) => s.prefs.appLockEnabled);
  const [unlocked, setUnlocked] = useState(false);
  const [prompting, setPrompting] = useState(false);

  const mustLock = hydrated && enabled && !unlocked;

  const prompt = useCallback(async () => {
    setPrompting(true);
    try {
      if (await authenticateBiometric('Unlock Australian Rates')) setUnlocked(true);
    } finally {
      setPrompting(false);
    }
  }, []);

  useEffect(() => {
    if (mustLock) void prompt();
  }, [mustLock, prompt]);

  if (!mustLock) return <>{children}</>;

  return (
    <View
      style={{
        flex: 1,
        backgroundColor: theme.colors.bg,
        alignItems: 'center',
        justifyContent: 'center',
        gap: 14,
        padding: 24,
      }}
    >
      <Ionicons name="lock-closed" size={40} color={theme.colors.primary} />
      <AppText variant="h3">Locked</AppText>
      <AppText variant="small" color="textMuted" style={{ textAlign: 'center' }}>
        Unlock with your fingerprint, face, or device PIN.
      </AppText>
      <Button title="Unlock" icon="finger-print" onPress={prompt} loading={prompting} disabled={prompting} />
    </View>
  );
}
