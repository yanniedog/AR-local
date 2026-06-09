import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import React, { useState } from 'react';
import { View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Chip } from '../src/components/ui';
import { AppText, Button, Row } from '../src/components/ui';
import { SECTIONS, SECTION_ORDER } from '../src/constants';
import { ensurePermissions, registerBackgroundRefresh } from '../src/data/notifications';
import { useStore } from '../src/data/store';
import type { SectionKey } from '../src/types';
import { useTheme } from '../src/theme/ThemeProvider';

export default function Onboarding() {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const completeOnboarding = useStore((s) => s.completeOnboarding);
  const [interests, setInterests] = useState<SectionKey[]>(['Mortgage', 'Savings', 'TD']);
  const [notify, setNotify] = useState(true);

  const toggle = (key: SectionKey) =>
    setInterests((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]));

  const start = async () => {
    if (notify) {
      const ok = await ensurePermissions();
      if (ok) void registerBackgroundRefresh();
      completeOnboarding(interests, ok);
    } else {
      completeOnboarding(interests, false);
    }
    router.replace('/(tabs)');
  };

  return (
    <View style={{ flex: 1, paddingTop: insets.top + 40, paddingHorizontal: 24, backgroundColor: theme.colors.bg }}>
      <View
        style={{
          width: 64,
          height: 64,
          borderRadius: 18,
          backgroundColor: theme.colors.primary,
          alignItems: 'center',
          justifyContent: 'center',
          marginBottom: 20,
        }}
      >
        <Ionicons name="trending-up" size={36} color={theme.colors.onPrimary} />
      </View>
      <AppText variant="h1">Australian Rates</AppText>
      <AppText variant="body" color="textMuted" style={{ marginTop: 8, lineHeight: 22 }}>
        Daily Australian home loan, savings and term-deposit rates — sourced from open
        banking (CDR) data and refreshed automatically. Works offline.
      </AppText>

      <AppText variant="h3" style={{ marginTop: 36, marginBottom: 12 }}>
        What are you interested in?
      </AppText>
      <Row gap={10} style={{ flexWrap: 'wrap' }}>
        {SECTION_ORDER.map((key) => (
          <Chip
            key={key}
            label={SECTIONS[key].title}
            icon={SECTIONS[key].icon as keyof typeof Ionicons.glyphMap}
            selected={interests.includes(key)}
            onPress={() => toggle(key)}
          />
        ))}
      </Row>

      <Row
        gap={12}
        style={{ marginTop: 28, alignItems: 'flex-start' }}
      >
        <Ionicons name="notifications-outline" size={22} color={theme.colors.primary} />
        <View style={{ flex: 1 }}>
          <AppText variant="body" weight="700">
            Rate-change alerts
          </AppText>
          <AppText variant="small" color="textMuted" style={{ marginTop: 2 }}>
            Get a local notification when best rates move or the RBA cash rate changes.
          </AppText>
        </View>
        <Chip label={notify ? 'On' : 'Off'} selected={notify} onPress={() => setNotify((v) => !v)} />
      </Row>

      <View style={{ flex: 1 }} />
      <Button title="Get started" icon="arrow-forward" onPress={start} style={{ marginBottom: insets.bottom + 20 }} />
    </View>
  );
}
