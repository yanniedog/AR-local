import { Ionicons } from '@expo/vector-icons';
import React from 'react';
import { Pressable } from 'react-native';

import { useTheme } from '../theme/ThemeProvider';
import { AppText, Row } from './ui';

export function MetricCard({
  icon,
  title,
  value,
  sub,
  accent,
  onPress,
}: {
  icon: keyof typeof Ionicons.glyphMap;
  title: string;
  value: string;
  sub?: string;
  accent?: string;
  onPress?: () => void;
}) {
  const theme = useTheme();
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => ({
        flex: 1,
        backgroundColor: theme.colors.card,
        borderRadius: theme.radius.lg,
        borderWidth: 1,
        borderColor: theme.colors.border,
        padding: 14,
        opacity: pressed ? 0.85 : 1,
      })}
    >
      <Row gap={6} style={{ marginBottom: 8 }}>
        <Ionicons name={icon} size={16} color={accent ?? theme.colors.primary} />
        <AppText variant="small" color="textMuted" numberOfLines={1} style={{ flex: 1 }}>
          {title}
        </AppText>
      </Row>
      <AppText variant="h2" weight="800" style={accent ? { color: accent } : undefined}>
        {value}
      </AppText>
      {sub ? (
        <AppText variant="tiny" color="textFaint" numberOfLines={1} style={{ marginTop: 2 }}>
          {sub}
        </AppText>
      ) : null}
    </Pressable>
  );
}
