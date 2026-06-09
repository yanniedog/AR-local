import { Ionicons } from '@expo/vector-icons';
import React from 'react';
import { View } from 'react-native';

import { useTheme } from '../theme/ThemeProvider';
import { AppText, Row } from './ui';

export function OfflineBanner({ source, offline }: { source: string; offline: boolean }) {
  const theme = useTheme();
  if (!offline && source !== 'sample') return null;
  const sample = source === 'sample';
  return (
    <Row
      gap={8}
      style={{
        backgroundColor: sample ? theme.colors.primaryMuted : theme.colors.chip,
        paddingHorizontal: 12,
        paddingVertical: 8,
        borderRadius: theme.radius.md,
        marginBottom: 12,
      }}
    >
      <Ionicons
        name={sample ? 'flask-outline' : 'cloud-offline-outline'}
        size={16}
        color={sample ? theme.colors.primary : theme.colors.warning}
      />
      <AppText variant="small" color="textMuted" style={{ flex: 1 }}>
        {sample
          ? 'Showing bundled sample data — connecting for the latest…'
          : 'Offline — showing the last downloaded rates.'}
      </AppText>
    </Row>
  );
}

export function EmptyState({
  icon = 'search',
  title,
  subtitle,
  fill,
}: {
  icon?: keyof typeof Ionicons.glyphMap;
  title: string;
  subtitle?: string;
  /** When true, fills the screen with the themed background (tab empty states). */
  fill?: boolean;
}) {
  const theme = useTheme();
  return (
    <View
      style={[
        { alignItems: 'center', paddingVertical: 48, paddingHorizontal: 24 },
        fill && { flex: 1, backgroundColor: theme.colors.bg, justifyContent: 'center' },
      ]}
    >
      <Ionicons name={icon} size={42} color={theme.colors.textFaint} />
      <AppText variant="h3" style={{ marginTop: 12, textAlign: 'center' }}>
        {title}
      </AppText>
      {subtitle ? (
        <AppText variant="small" color="textMuted" style={{ marginTop: 6, textAlign: 'center' }}>
          {subtitle}
        </AppText>
      ) : null}
    </View>
  );
}

export function LoadingRows({ count = 6 }: { count?: number }) {
  const theme = useTheme();
  return (
    <View>
      {Array.from({ length: count }).map((_, i) => (
        <View
          key={i}
          style={{
            height: 76,
            borderRadius: theme.radius.lg,
            backgroundColor: theme.colors.skeleton,
            marginBottom: 10,
          }}
        />
      ))}
    </View>
  );
}
