/**
 * Palette tokens aligned with Pi dashboard shell CSS (`site/foundation.css`).
 * Dark is the dashboard default (`data-theme="dark"` on `dashboard/index.html`).
 */
export interface Palette {
  bg: string;
  surface: string;
  surfaceAlt: string;
  card: string;
  border: string;
  text: string;
  textMuted: string;
  textFaint: string;
  primary: string;
  primaryMuted: string;
  onPrimary: string;
  success: string;
  warning: string;
  danger: string;
  chip: string;
  chipText: string;
  shadow: string;
  skeleton: string;
  overlay: string;
  /** Mortgage section accent (`public-polish.css` home-loans). */
  sectionAccent: string;
}

export const DARK: Palette = {
  bg: '#0b0e11',
  surface: '#161d26',
  surfaceAlt: '#12181f',
  card: '#1b2530',
  border: '#2a3442',
  text: '#edf3f9',
  textMuted: '#98a6b5',
  textFaint: '#6f7d8c',
  primary: '#2563eb',
  primaryMuted: '#1e2a3d',
  onPrimary: '#ffffff',
  success: '#1fb978',
  warning: '#f59e0b',
  danger: '#ef4444',
  chip: '#1b2530',
  chipText: '#c5ced8',
  shadow: '#00000088',
  skeleton: '#212d3a',
  overlay: '#05080cb8',
  sectionAccent: '#3b82f6',
};

export const LIGHT: Palette = {
  bg: '#f3f6fa',
  surface: '#ffffff',
  surfaceAlt: '#edf2f8',
  card: '#ffffff',
  border: '#dce3eb',
  text: '#102033',
  textMuted: '#4f6276',
  textFaint: '#7a8a9a',
  primary: '#2563eb',
  primaryMuted: '#e8effd',
  onPrimary: '#ffffff',
  success: '#0a6d49',
  warning: '#8a4b00',
  danger: '#c2410c',
  chip: '#eef3f8',
  chipText: '#24364a',
  shadow: '#10203316',
  skeleton: '#e7ecf4',
  overlay: '#10203347',
  sectionAccent: '#3b82f6',
};
