import { Platform, type TextStyle } from 'react-native';

import type { Theme } from '../theme/theme';

/** M3 top app bar defaults for stack screens on Android. */
export function androidStackScreenOptions(theme: Theme) {
  if (Platform.OS !== 'android') return {};

  return {
    headerStyle: { backgroundColor: theme.colors.surfaceAlt },
    headerTitleStyle: {
      color: theme.colors.text,
      fontWeight: '500' as TextStyle['fontWeight'],
      fontSize: 22,
      letterSpacing: 0,
    },
    headerTitleAlign: 'center' as const,
    headerBackTitleVisible: false,
    headerShadowVisible: false,
  };
}

/** M3 navigation bar height (icon + label + padding, excluding safe-area inset). */
export const M3_NAV_BAR_HEIGHT = 80;
