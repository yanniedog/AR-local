import type { ColorSchemeName } from 'react-native';

import { DARK, LIGHT, type Palette } from './colors';

export interface Theme {
  dark: boolean;
  colors: Palette;
  spacing: (n: number) => number;
  radius: { sm: number; md: number; lg: number; xl: number; pill: number };
  font: {
    h1: number;
    h2: number;
    h3: number;
    body: number;
    small: number;
    tiny: number;
  };
}

const base = {
  spacing: (n: number) => n * 4,
  radius: { sm: 8, md: 12, lg: 16, xl: 22, pill: 999 },
  font: { h1: 30, h2: 22, h3: 17, body: 15, small: 13, tiny: 11 },
};

export const darkTheme: Theme = { dark: true, colors: DARK, ...base };
export const lightTheme: Theme = { dark: false, colors: LIGHT, ...base };

export type ThemeMode = 'system' | 'light' | 'dark';

/** Resolve persisted theme mode + OS appearance to a concrete theme object. */
export function resolveTheme(mode: ThemeMode, scheme: ColorSchemeName | null | undefined): Theme {
  const resolved = mode === 'system' ? scheme ?? 'dark' : mode;
  return resolved === 'light' ? lightTheme : darkTheme;
}
