import { createMaterial3Theme } from '@pchmn/expo-material3-theme';

import { BRAND_SOURCE_COLOR, paletteFromM3Scheme } from '../src/theme/m3Palette';
import { darkTheme, lightTheme, resolveM3Theme, resolveTheme } from '../src/theme/theme';

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
  const material3 = createMaterial3Theme({ sourceColor: BRAND_SOURCE_COLOR });

  it('maps surfaceContainer roles onto palette elevation tokens', () => {
    const dark = paletteFromM3Scheme(material3.dark, true);
    expect(dark.bg).toBe(material3.dark.background);
    expect(dark.surface).toBe(material3.dark.surface);
    expect(dark.surfaceAlt).toBe(material3.dark.surfaceContainerLow);
    expect(dark.card).toBe(material3.dark.surfaceContainerHigh);
    expect(dark.chip).toBe(material3.dark.surfaceContainer);
    expect(dark.skeleton).toBe(material3.dark.surfaceContainerHighest);
  });

  it('keeps fixed semantic status colors', () => {
    const dark = paletteFromM3Scheme(material3.dark, true);
    const light = paletteFromM3Scheme(material3.light, false);
    expect(dark.success).toBe(darkTheme.colors.success);
    expect(light.warning).toBe(lightTheme.colors.warning);
  });
});

describe('resolveM3Theme', () => {
  const material3 = createMaterial3Theme({ sourceColor: BRAND_SOURCE_COLOR });

  it('builds a dynamic theme for the resolved appearance', () => {
    const theme = resolveM3Theme('dark', 'light', material3);
    expect(theme.dark).toBe(true);
    expect(theme.colors.primary).toBe(material3.dark.primary);
    expect(theme.colors.card).toBe(material3.dark.surfaceContainerHigh);
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
});
