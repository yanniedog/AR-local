import React from 'react';
import {
  ScrollView,
  type ScrollViewProps,
  View,
  type ViewProps,
  type ViewStyle,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useStore } from '../data/store';
import type { Theme } from '../theme/theme';
import { useTheme } from '../theme/ThemeProvider';
import { DataHealthBanner } from './feedback';

const BANNER_WRAP = { paddingHorizontal: 16, paddingTop: 12 } as const;

/** Shared data-health strip for tab and stack screens. */
export function DataHealthBannerStrip() {
  const source = useStore((s) => s.source);
  const offline = useStore((s) => s.offline);
  return (
    <View style={BANNER_WRAP}>
      <DataHealthBanner source={source} offline={offline} />
    </View>
  );
}

/** Horizontal + top padding for fixed screen headers (toolbars). */
export function screenEdgeStyle(theme: Theme): ViewStyle {
  return {
    paddingHorizontal: theme.spacing(4),
    paddingTop: theme.spacing(3),
    gap: theme.spacing(3),
  };
}

/** Scroll/list body padding — 8pt grid with safe-area bottom inset. */
export function screenScrollContentStyle(theme: Theme, bottomInset = 0): ViewStyle {
  return {
    paddingHorizontal: theme.spacing(4),
    paddingTop: theme.spacing(3),
    paddingBottom: theme.spacing(6) + bottomInset,
    gap: theme.spacing(3),
  };
}

/** Static screen body with enforced spatial scaffold. */
export function ScreenContent({ style, children, ...rest }: ViewProps) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  return (
    <View style={[screenScrollContentStyle(theme, insets.bottom), style]} {...rest}>
      {children}
    </View>
  );
}

/** Full-screen container with themed background (tabs, stack bodies). */
export function Screen({
  style,
  children,
  showDataHealthBanner = true,
  ...rest
}: ViewProps & { showDataHealthBanner?: boolean }) {
  const theme = useTheme();
  return (
    <View style={[{ flex: 1, backgroundColor: theme.colors.bg }, style]} {...rest}>
      {showDataHealthBanner ? <DataHealthBannerStrip /> : null}
      {children}
    </View>
  );
}

/** Scrollable screen body; sets both scroll surface and overscroll background. */
export function ScreenScrollView({
  style,
  contentContainerStyle,
  children,
  showDataHealthBanner = true,
  ...rest
}: ScrollViewProps & { showDataHealthBanner?: boolean }) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  return (
    <ScrollView
      style={[{ flex: 1, backgroundColor: theme.colors.bg }, style]}
      contentContainerStyle={[screenScrollContentStyle(theme, insets.bottom), contentContainerStyle]}
      {...rest}
    >
      {showDataHealthBanner ? <DataHealthBannerStrip /> : null}
      {children}
    </ScrollView>
  );
}
