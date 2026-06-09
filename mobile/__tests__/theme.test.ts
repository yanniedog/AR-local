import { darkTheme, lightTheme, resolveTheme } from '../src/theme/theme';

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

describe('theme palettes', () => {
  it('includes overlay token in both palettes', () => {
    expect(lightTheme.colors.overlay).toMatch(/^#/);
    expect(darkTheme.colors.overlay).toMatch(/^#/);
  });

  it('matches Pi dashboard foundation.css accents and backgrounds', () => {
    expect(darkTheme.colors.bg).toBe('#0b0e11');
    expect(lightTheme.colors.bg).toBe('#f3f6fa');
    expect(darkTheme.colors.primary).toBe('#2563eb');
    expect(lightTheme.colors.primary).toBe('#2563eb');
    expect(darkTheme.colors.sectionAccent).toBe('#3b82f6');
    expect(lightTheme.colors.sectionAccent).toBe('#3b82f6');
  });
});
