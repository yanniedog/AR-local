import type { Material3Theme } from '@pchmn/expo-material3-theme';
import type { ColorSchemeName } from 'react-native';

import { DARK, LIGHT, type Palette } from './colors';
import { paletteFromM3Scheme } from './m3Palette';

export type FontVariant =
  | 'h1'
  | 'h2'
  | 'h3'
  | 'body'
  | 'small'
  | 'tiny'
  | 'rate'
  | 'rateHero';

export interface Theme {
  dark: boolean;
  colors: Palette;
  spacing: (n: number) => number;
  radius: { sm: number; md: number; lg: number; xl: number; pill: number };
  font: Record<FontVariant, number>;
  lineHeight: Record<FontVariant, number>;
}

const base = {
  spacing: (n: number) => n * 4,
  // Dashboard shell radii: panels/cards 12px, stat chips 8px, hero title scale ~1.35rem.
  radius: { sm: 8, md: 12, lg: 12, xl: 16, pill: 999 },
  font: { h1: 28, h2: 22, h3: 16, body: 15, small: 13, tiny: 11, rate: 20, rateHero: 28 },
  lineHeight: { h1: 34, h2: 28, h3: 22, body: 22, small: 18, tiny: 16, rate: 24, rateHero: 34 },
};

export const darkTheme: Theme = { dark: true, colors: DARK, ...base };
export const lightTheme: Theme = { dark: false, colors: LIGHT, ...base };

export type ThemeMode = 'system' | 'light' | 'dark';

function isDarkMode(mode: ThemeMode, scheme: ColorSchemeName | null | undefined): boolean {
  const resolved = mode === 'system' ? scheme ?? 'dark' : mode;
  return resolved !== 'light';
}

/** Resolve persisted theme mode + OS appearance to a static fallback theme object. */
export function resolveTheme(mode: ThemeMode, scheme: ColorSchemeName | null | undefined): Theme {
  return isDarkMode(mode, scheme) ? darkTheme : lightTheme;
}

/** Build a theme from Material 3 dynamic/system tokens mapped onto Palette. */
export function resolveM3Theme(
  mode: ThemeMode,
  scheme: ColorSchemeName | null | undefined,
  material3: Material3Theme,
): Theme {
  const dark = isDarkMode(mode, scheme);
  const m3Scheme = dark ? material3.dark : material3.light;
  return { dark, colors: paletteFromM3Scheme(m3Scheme, dark), ...base };
}
