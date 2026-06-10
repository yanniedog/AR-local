import { Ionicons } from '@expo/vector-icons';
import React, { useRef } from 'react';
import { Pressable, StyleSheet, View, type StyleProp, type ViewStyle } from 'react-native';
import { Swipeable } from 'react-native-gesture-handler';

import { useTheme } from '../theme/ThemeProvider';

function marginBottomFromStyle(style?: StyleProp<ViewStyle>): number {
  const flat = StyleSheet.flatten(style);
  return typeof flat?.marginBottom === 'number' ? flat.marginBottom : 0;
}

export function SwipeableRow({
  children,
  onDelete,
  enabled = true,
  style,
  deleteLabel = 'Remove',
}: {
  children: React.ReactNode;
  onDelete: () => void;
  enabled?: boolean;
  style?: StyleProp<ViewStyle>;
  deleteLabel?: string;
}) {
  const theme = useTheme();
  const ref = useRef<Swipeable>(null);

  const handleDelete = () => {
    ref.current?.close();
    onDelete();
  };

  const renderRightActions = () => (
    <Pressable
      onPress={handleDelete}
      accessibilityRole="button"
      accessibilityLabel={deleteLabel}
      style={{
        backgroundColor: theme.colors.danger,
        justifyContent: 'center',
        alignItems: 'center',
        width: 80,
        marginBottom: marginBottomFromStyle(style),
        borderTopRightRadius: theme.radius.lg,
        borderBottomRightRadius: theme.radius.lg,
      }}
    >
      <Ionicons name="trash-outline" size={22} color={theme.colors.onPrimary} />
    </Pressable>
  );

  if (!enabled) {
    return <View style={style}>{children}</View>;
  }

  return (
    <Swipeable
      ref={ref}
      renderRightActions={renderRightActions}
      overshootRight={false}
      friction={2}
      rightThreshold={40}
      onSwipeableOpen={handleDelete}
    >
      <View style={style}>{children}</View>
    </Swipeable>
  );
}
