/**
 * App-facing color tokens. Runtime values come from Material 3 dynamic/system
 * schemes mapped in `m3Palette.ts`; DARK/LIGHT remain static fallbacks for tests
 * and non-M3 paths.
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
  rba: string;
  onRba: string;
  rateLoan: string;
  rateDeposit: string;
  favorite: string;
}

export function withAlpha(hex: string, alpha: number): string {
  const n = hex.replace('#', '');
  const r = parseInt(n.slice(0, 2), 16);
  const g = parseInt(n.slice(2, 4), 16);
  const b = parseInt(n.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

export const DARK: Palette = {
  bg: '#0b0e11', surface: '#161d26', surfaceAlt: '#12181f', card: '#1b2530', border: '#2a3442',
  text: '#edf3f9', textMuted: '#98a6b5', textFaint: '#6f7d8c', primary: '#2563eb', primaryMuted: '#1e2a3d',
  onPrimary: '#ffffff', success: '#1fb978', warning: '#f59e0b', danger: '#ef4444', chip: '#1b2530',
  chipText: '#c5ced8', shadow: '#00000088', skeleton: '#212d3a', overlay: '#05080cb8',
  rba: '#f59e0b', onRba: '#0b0e11', rateLoan: '#1fb978', rateDeposit: '#3b82f6', favorite: '#eab308',
};

export const LIGHT: Palette = {
  bg: '#f3f6fa', surface: '#ffffff', surfaceAlt: '#edf2f8', card: '#ffffff', border: '#dce3eb',
  text: '#102033', textMuted: '#4f6276', textFaint: '#7a8a9a', primary: '#2563eb', primaryMuted: '#e8effd',
  onPrimary: '#ffffff', success: '#0a6d49', warning: '#8a4b00', danger: '#c2410c', chip: '#eef3f8',
  chipText: '#24364a', shadow: '#10203316', skeleton: '#e7ecf4', overlay: '#10203347',
  rba: '#b45309', onRba: '#ffffff', rateLoan: '#0a6d49', rateDeposit: '#2563eb', favorite: '#ca8a04',
};
