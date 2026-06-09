import React from 'react';
import {
  ScrollView,
  type ScrollViewProps,
  View,
  type ViewProps,
} from 'react-native';

import { useTheme } from '../theme/ThemeProvider';

/** Full-screen container with themed background (tabs, stack bodies). */
export function Screen({ style, children, ...rest }: ViewProps) {
  const theme = useTheme();
  return (
    <View style={[{ flex: 1, backgroundColor: theme.colors.bg }, style]} {...rest}>
      {children}
    </View>
  );
}

/** Scrollable screen body; sets both scroll surface and overscroll background. */
export function ScreenScrollView({
  style,
  contentContainerStyle,
  children,
  ...rest
}: ScrollViewProps) {
  const theme = useTheme();
  return (
    <ScrollView
      style={[{ flex: 1, backgroundColor: theme.colors.bg }, style]}
      contentContainerStyle={contentContainerStyle}
      {...rest}
    >
      {children}
    </ScrollView>
  );
}
