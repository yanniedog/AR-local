import React from 'react';
import { Pressable, View } from 'react-native';

import type { UndoSnack } from '../hooks/useUndoSnackbar';
import { useTheme } from '../theme/ThemeProvider';
import { AppText } from './ui';

export function UndoSnackbar({
  snack,
  onUndo,
}: {
  snack: UndoSnack | null;
  onUndo: () => void;
}) {
  const theme = useTheme();
  if (!snack) return null;

  return (
    <View
      pointerEvents="box-none"
      style={{
        position: 'absolute',
        left: 16,
        right: 16,
        bottom: 16,
        zIndex: 100,
      }}
    >
      <View
        style={{
          flexDirection: 'row',
          alignItems: 'center',
          gap: 12,
          paddingHorizontal: 16,
          paddingVertical: 14,
          borderRadius: theme.radius.md,
          backgroundColor: theme.colors.card,
          borderWidth: 1,
          borderColor: theme.colors.border,
          shadowColor: '#000',
          shadowOffset: { width: 0, height: 4 },
          shadowOpacity: theme.dark ? 0.35 : 0.12,
          shadowRadius: 8,
          elevation: 6,
        }}
      >
        <AppText variant="small" style={{ flex: 1 }}>
          {snack.message}
        </AppText>
        <Pressable
          onPress={onUndo}
          hitSlop={8}
          accessibilityRole="button"
          accessibilityLabel="Undo"
          style={({ pressed }) => ({ opacity: pressed ? 0.7 : 1 })}
        >
          <AppText variant="small" weight="700" style={{ color: theme.colors.primary }}>
            Undo
          </AppText>
        </Pressable>
      </View>
    </View>
  );
}
