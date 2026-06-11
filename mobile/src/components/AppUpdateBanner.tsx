import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { useEffect, useState } from 'react';
import { Platform, Pressable } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useStore } from '../data/store';
import { checkForAppUpdate, type ApkManifest, type UpdateCheckResult } from '../lib/appUpdate';
import { shouldShowUpdateBanner } from '../lib/updateBanner';
import { useTheme } from '../theme/ThemeProvider';
import { AppText, Row } from './ui';

export interface AppUpdateBannerState {
  visible: boolean;
  remote: ApkManifest | null;
  dismiss: () => void;
}

/**
 * One update check per app session; banner visibility persists dismissal
 * per build_number, so it returns when the next release ships.
 */
export function useAppUpdateBanner(): AppUpdateBannerState {
  const dismissedBuild = useStore((s) => s.prefs.dismissedUpdateBuild);
  const setPref = useStore((s) => s.setPref);
  const [result, setResult] = useState<UpdateCheckResult | null>(null);

  useEffect(() => {
    if (Platform.OS !== 'android') return;
    let cancelled = false;
    checkForAppUpdate()
      .then((r) => {
        if (!cancelled) setResult(r);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const available = result?.status === 'available' ? result : null;
  return {
    visible: shouldShowUpdateBanner(result, dismissedBuild),
    remote: available?.remote ?? null,
    dismiss: () => {
      if (available) setPref('dismissedUpdateBuild', available.remote.build_number);
    },
  };
}

/** Dismissible top-of-app banner shown when a newer APK is published. */
export function AppUpdateBanner({ remote, onDismiss }: { remote: ApkManifest; onDismiss: () => void }) {
  const theme = useTheme();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  return (
    <Row
      gap={8}
      style={{
        backgroundColor: theme.colors.surfaceAlt,
        borderBottomColor: theme.colors.border,
        borderBottomWidth: 1,
        paddingHorizontal: 14,
        paddingTop: insets.top + 6,
        paddingBottom: 8,
      }}
      accessible
      accessibilityRole="alert"
      accessibilityLabel={`App update ${remote.version} available`}
    >
      <Ionicons name="cloud-download-outline" size={16} color={theme.colors.primary} />
      <AppText variant="small" weight="600" numberOfLines={1} style={{ flex: 1 }}>
        Update available — v{remote.version}
      </AppText>
      <Pressable
        onPress={() => router.push('/settings')}
        accessibilityRole="button"
        accessibilityLabel="Open settings to install the update"
        hitSlop={8}
      >
        <AppText variant="small" weight="800" style={{ color: theme.colors.primary }}>
          View
        </AppText>
      </Pressable>
      <Pressable
        onPress={onDismiss}
        accessibilityRole="button"
        accessibilityLabel="Dismiss update banner"
        hitSlop={8}
      >
        <Ionicons name="close" size={18} color={theme.colors.textMuted} />
      </Pressable>
    </Row>
  );
}
