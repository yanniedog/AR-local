import { Ionicons } from '@expo/vector-icons';
import React from 'react';
import { Alert, Pressable, View } from 'react-native';

import { useTheme } from '../theme/ThemeProvider';
import { SwipeableRow } from './SwipeableRow';
import { AppText } from './ui';

/** Material list row minimum height (dp). */
const ROW_MIN_HEIGHT = 48;

export function SubscriptionRow({
  kind,
  label,
  onSwipeRemove,
  onConfirmRemove,
}: {
  kind: 'Product' | 'Search';
  label: string;
  /** Swipe-to-delete — caller shows undo snackbar after removal. */
  onSwipeRemove: () => void;
  /** Tap close — confirm before removing. */
  onConfirmRemove: () => void;
}) {
  const theme = useTheme();

  const confirmRemove = () => {
    Alert.alert('Remove subscription?', label, [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Remove', style: 'destructive', onPress: onConfirmRemove },
    ]);
  };

  return (
    <SwipeableRow
      onDelete={onSwipeRemove}
      deleteLabel="Remove subscription"
      style={{ marginBottom: 4 }}
    >
      <View
        style={{
          flexDirection: 'row',
          alignItems: 'center',
          gap: 10,
          minHeight: ROW_MIN_HEIGHT,
          paddingHorizontal: 2,
        }}
      >
        <View style={{ flex: 1, justifyContent: 'center' }}>
          <AppText variant="tiny" color="textFaint" numberOfLines={1}>
            {kind}
          </AppText>
          <AppText variant="small" weight="600" numberOfLines={1}>
            {label}
          </AppText>
        </View>
        <Pressable
          onPress={confirmRemove}
          hitSlop={10}
          accessibilityRole="button"
          accessibilityLabel="Remove subscription"
          style={({ pressed }) => ({
            minWidth: ROW_MIN_HEIGHT,
            minHeight: ROW_MIN_HEIGHT,
            alignItems: 'center',
            justifyContent: 'center',
            opacity: pressed ? 0.7 : 1,
          })}
        >
          <Ionicons name="close-circle-outline" size={22} color={theme.colors.textMuted} />
        </Pressable>
      </View>
    </SwipeableRow>
  );
}
