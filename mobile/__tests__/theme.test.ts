import { BRAND_SOURCE_COLOR, paletteFromM3Scheme } from '../src/theme/m3Palette';
import { darkTheme, lightTheme, resolveM3Theme, resolveTheme } from '../src/theme/theme';
import type { Material3Scheme, Material3Theme } from '@pchmn/expo-material3-theme';

const mockDarkScheme: Material3Scheme = {
  primary: '#8ab4f8',
  onPrimary: '#062e6f',
  primaryContainer: '#1e2a3d',
  onPrimaryContainer: '#d3e3fd',
  secondary: '#bec8d6',
  onSecondary: '#28323f',
  secondaryContainer: '#3e4855',
  onSecondaryContainer: '#dae3f0',
  tertiary: '#3b82f6',
  onTertiary: '#ffffff',
  tertiaryContainer: '#1b3a6b',
  onTertiaryContainer: '#d3e3fd',
  background: '#0b0e11',
  onBackground: '#edf3f9',
  surface: '#161d26',
  onSurface: '#edf3f9',
  surfaceVariant: '#2a3442',
  onSurfaceVariant: '#98a6b5',
  outline: '#6f7d8c',
  outlineVariant: '#2a3442',
  inverseSurface: '#edf3f9',
  inverseOnSurface: '#102033',
  inversePrimary: '#2563eb',
  error: '#ef4444',
  onError: '#ffffff',
  errorContainer: '#93000a',
  onErrorContainer: '#ffdad6',
  shadow: '#000000',
  scrim: '#05080cb8',
  surfaceDisabled: '#161d2661',
  onSurfaceDisabled: '#edf3f961',
  backdrop: '#05080cb8',
  surfaceContainer: '#1b2530',
  surfaceContainerLow: '#12181f',
  surfaceContainerLowest: '#0b0e11',
  surfaceContainerHigh: '#212d3a',
  surfaceContainerHighest: '#2a3442',
  surfaceBright: '#3a4654',
  surfaceDim: '#0b0e11',
  surfaceTint: '#8ab4f8',
  elevation: {
    level0: 'transparent',
    level1: '#161d26',
    level2: '#1b2530',
    level3: '#212d3a',
    level4: '#2a3442',
    level5: '#3a4654',
  },
};

const mockLightScheme: Material3Scheme = {
  ...mockDarkScheme,
  background: '#f3f6fa',
  onBackground: '#102033',
  surface: '#ffffff',
  onSurface: '#102033',
  onSurfaceVariant: '#4f6276',
  outline: '#7a8a9a',
  outlineVariant: '#dce3eb',
  surfaceContainer: '#eef3f8',
  surfaceContainerLow: '#edf2f8',
  surfaceContainerLowest: '#ffffff',
  surfaceContainerHigh: '#ffffff',
  surfaceContainerHighest: '#e7ecf4',
  primary: '#2563eb',
  primaryContainer: '#e8effd',
  scrim: '#10203347',
};

const mockMaterial3: Material3Theme = { dark: mockDarkScheme, light: mockLightScheme };

describe('resolveTheme', () => {
  it('returns light theme when mode is light', () => {
    expect(resolveTheme('light', 'dark')).toBe(lightTheme);
  });

  it('returns dark theme when mode is dark', () => {
    expect(resolveTheme('dark', 'light')).toBe(darkTheme);
  });

  it('follows system appearance when mode is system', () => {
    expect(resolveTheme('system', 'light')).toBe(lightTheme);
    expect(resolveTheme('system', 'dark')).toBe(darkTheme);
  });

  it('defaults to dark when system appearance is unknown', () => {
    expect(resolveTheme('system', null)).toBe(darkTheme);
    expect(resolveTheme('system', undefined)).toBe(darkTheme);
  });
});

describe('paletteFromM3Scheme', () => {
  it('maps surfaceContainer roles onto palette elevation tokens', () => {
    const dark = paletteFromM3Scheme(mockDarkScheme, true);
    expect(dark.bg).toBe(mockDarkScheme.background);
    expect(dark.surface).toBe(mockDarkScheme.surface);
    expect(dark.surfaceAlt).toBe(mockDarkScheme.surfaceContainerLow);
    expect(dark.card).toBe(mockDarkScheme.surfaceContainerHigh);
    expect(dark.chip).toBe(mockDarkScheme.surfaceContainer);
    expect(dark.skeleton).toBe(mockDarkScheme.surfaceContainerHighest);
  });

  it('keeps fixed semantic status colors', () => {
    const dark = paletteFromM3Scheme(mockDarkScheme, true);
    const light = paletteFromM3Scheme(mockLightScheme, false);
    expect(dark.success).toBe(darkTheme.colors.success);
    expect(light.warning).toBe(lightTheme.colors.warning);
  });
});

describe('resolveM3Theme', () => {
  it('builds a dynamic theme for the resolved appearance', () => {
    const theme = resolveM3Theme('dark', 'light', mockMaterial3);
    expect(theme.dark).toBe(true);
    expect(theme.colors.primary).toBe(mockDarkScheme.primary);
    expect(theme.colors.card).toBe(mockDarkScheme.surfaceContainerHigh);
  });
});

describe('theme palettes', () => {
  it('includes overlay token in both palettes', () => {
    expect(lightTheme.colors.overlay).toMatch(/^#/);
    expect(darkTheme.colors.overlay).toMatch(/^#/);
  });

  it('keeps static fallback palettes for tests and non-M3 paths', () => {
    expect(darkTheme.colors.bg).toBe('#0b0e11');
    expect(lightTheme.colors.bg).toBe('#f3f6fa');
    expect(darkTheme.colors.primary).toBe('#2563eb');
    expect(lightTheme.colors.primary).toBe('#2563eb');
    expect(darkTheme.colors.sectionAccent).toBe('#3b82f6');
    expect(lightTheme.colors.sectionAccent).toBe('#3b82f6');
  });

  it('includes rate typography tokens and line heights', () => {
    expect(lightTheme.font.rate).toBe(20);
    expect(lightTheme.font.rateHero).toBe(28);
    expect(lightTheme.lineHeight.rate).toBe(24);
    expect(lightTheme.lineHeight.rateHero).toBe(34);
    expect(darkTheme.lineHeight.body).toBe(22);
  });

  it('exports brand seed for Material You fallback', () => {
    expect(BRAND_SOURCE_COLOR).toBe('#2563eb');
  });
});
