import { Ionicons } from '@expo/vector-icons';
import React from 'react';
import { View } from 'react-native';

import { useStore } from '../data/store';
import { useTheme } from '../theme/ThemeProvider';
import { BrandLockup } from './BrandLockup';
import { Screen } from './Screen';
import { AppText, Button } from './ui';

/** Full-screen recovery when store.status === 'error' (no usable payload). */
export function DataUnavailableScreen() {
  const theme = useTheme();
  const error = useStore((s) => s.error);
  const refreshing = useStore((s) => s.refreshing);
  const status = useStore((s) => s.status);
  const retryDataLoad = useStore((s) => s.retryDataLoad);
  const loadSampleFallback = useStore((s) => s.loadSampleFallback);
  const busy = refreshing || status === 'loading';

  return (
    <Screen style={{ justifyContent: 'center', paddingHorizontal: 28 }}>
      <View
        style={{
          backgroundColor: theme.colors.card,
          borderRadius: theme.radius.xl,
          padding: 24,
          alignItems: 'center',
          maxWidth: 420,
          width: '100%',
          alignSelf: 'center',
          borderWidth: 1,
          borderColor: theme.colors.border,
        }}
      >
        <BrandLockup markSize={32} style={{ marginBottom: 20 }} />
        <Ionicons name="cloud-offline-outline" size={40} color={theme.colors.primary} />
        <AppText variant="h2" style={{ marginTop: 14, textAlign: 'center' }}>
          Data unavailable
        </AppText>
        <AppText variant="small" color="textMuted" style={{ marginTop: 8, textAlign: 'center', lineHeight: 20 }}>
          We could not load rates. Check your connection and try again, or use bundled sample data offline.
        </AppText>
        {error ? (
          <AppText variant="tiny" color="textMuted" style={{ marginTop: 10, textAlign: 'center' }} numberOfLines={4}>
            {error}
          </AppText>
        ) : null}
        <View style={{ marginTop: 22, width: '100%', gap: 10 }}>
          <Button title="Try again" icon="refresh" onPress={() => void retryDataLoad()} loading={busy} disabled={busy} />
          <Button
            title="Use sample data"
            variant="secondary"
            icon="flask-outline"
            onPress={() => void loadSampleFallback()}
            disabled={busy}
          />
        </View>
      </View>
    </Screen>
  );
}
