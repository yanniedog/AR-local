import { Ionicons } from '@expo/vector-icons';
import React from 'react';
import { Pressable, View } from 'react-native';

import { useTheme } from '../theme/ThemeProvider';
import { AppText } from './ui';

/** 44×44 toolbar icon control — Browse and Search chrome. */
export function ToolbarIconButton({
  icon,
  onPress,
  accessibilityLabel,
  accessibilityHint,
  active,
  badge,
}: {
  icon: keyof typeof Ionicons.glyphMap;
  onPress: () => void;
  accessibilityLabel?: string;
  accessibilityHint?: string;
  active?: boolean;
  badge?: number;
}) {
  const theme = useTheme();
  return (
    <View>
      <Pressable
        onPress={onPress}
        accessibilityLabel={accessibilityLabel}
        accessibilityHint={accessibilityHint}
        style={{
          backgroundColor: active ? theme.colors.primaryMuted : theme.colors.surfaceAlt,
          borderRadius: theme.radius.md,
          paddingHorizontal: theme.spacing(3),
          height: 44,
          justifyContent: 'center',
        }}
      >
        <Ionicons name={icon} size={20} color={active ? theme.colors.primary : theme.colors.text} />
      </Pressable>
      {badge ? (
        <View
          style={{
            position: 'absolute',
            top: -theme.spacing(1),
            right: -theme.spacing(1),
            backgroundColor: theme.colors.primary,
            borderRadius: theme.radius.pill,
            minWidth: 18,
            height: 18,
            alignItems: 'center',
            justifyContent: 'center',
            paddingHorizontal: theme.spacing(1),
          }}
        >
          <AppText variant="tiny" weight="800" style={{ color: theme.colors.onPrimary }}>
            {badge}
          </AppText>
        </View>
      ) : null}
    </View>
  );
}
