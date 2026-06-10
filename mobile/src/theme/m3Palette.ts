import type { Material3Scheme } from '@pchmn/expo-material3-theme';

import { DARK, LIGHT, type Palette } from './colors';

/** Brand seed when Material You / dynamic color is unavailable (iOS, older Android, Expo Go). */
export const BRAND_SOURCE_COLOR = '#2563eb';

/** Status colors stay fixed across dynamic schemes so rate semantics stay recognizable. */
const SEMANTIC = {
  dark: {
    success: DARK.success,
    warning: DARK.warning,
    danger: DARK.danger,
  },
  light: {
    success: LIGHT.success,
    warning: LIGHT.warning,
    danger: LIGHT.danger,
  },
} as const;

/**
 * Map Material 3 scheme roles onto the app Palette.
 * Surface hierarchy uses surfaceContainer* tokens for tonal elevation.
 */
export function paletteFromM3Scheme(scheme: Material3Scheme, dark: boolean): Palette {
  const semantic = dark ? SEMANTIC.dark : SEMANTIC.light;
  return {
    bg: scheme.background,
    surface: scheme.surface,
    surfaceAlt: scheme.surfaceContainerLow,
    card: scheme.surfaceContainerHigh,
    border: scheme.outlineVariant,
    text: scheme.onSurface,
    textMuted: scheme.onSurfaceVariant,
    textFaint: scheme.outline,
    primary: scheme.primary,
    primaryMuted: scheme.primaryContainer,
    onPrimary: scheme.onPrimary,
    success: semantic.success,
    warning: semantic.warning,
    danger: semantic.danger,
    chip: scheme.surfaceContainer,
    chipText: scheme.onSurfaceVariant,
    shadow: scheme.shadow,
    skeleton: scheme.surfaceContainerHighest,
    overlay: scheme.scrim,
    sectionAccent: scheme.tertiary,
  };
}
