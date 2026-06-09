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
}

export const DARK: Palette = {
  bg: '#0b0f17',
  surface: '#121826',
  surfaceAlt: '#0e1420',
  card: '#161d2e',
  border: '#232c40',
  text: '#e6edf7',
  textMuted: '#9aa7bd',
  textFaint: '#6b7891',
  primary: '#60a5fa',
  primaryMuted: '#16263f',
  onPrimary: '#04122b',
  success: '#3fb950',
  warning: '#d29922',
  danger: '#f85149',
  chip: '#1c2438',
  chipText: '#c3cee0',
  shadow: '#00000088',
  skeleton: '#1b2334',
  overlay: '#00000066',
};

export const LIGHT: Palette = {
  bg: '#f4f6fb',
  surface: '#ffffff',
  surfaceAlt: '#eef2f9',
  card: '#ffffff',
  border: '#e2e8f2',
  text: '#0b1220',
  textMuted: '#5b6678',
  textFaint: '#8b95a7',
  primary: '#3b82f6',
  primaryMuted: '#dbeafe',
  onPrimary: '#ffffff',
  success: '#1a7f37',
  warning: '#9a6700',
  danger: '#cf222e',
  chip: '#eef2f9',
  chipText: '#3a4254',
  shadow: '#0b122016',
  skeleton: '#e7ecf4',
  overlay: '#0b122040',
};
