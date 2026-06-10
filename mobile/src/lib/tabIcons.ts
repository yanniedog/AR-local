/** expo-router tab route names under `app/(tabs)/`. */
export const TAB_ROUTES = ['index', 'browse', 'watchlist', 'trends', 'settings'] as const;

export type TabRouteName = (typeof TAB_ROUTES)[number];

/** Ionicons glyph names used on iOS tab bar. */
export type TabIoniconName = 'home' | 'list' | 'star' | 'stats-chart' | 'settings';

/** Human-readable labels for the bottom navigation bar. */
export const TAB_LABELS: Record<TabRouteName, string> = {
  index: 'Home',
  browse: 'Browse',
  watchlist: 'Watchlist',
  trends: 'Trends',
  settings: 'Settings',
};

/** Material Symbols ligature names (Outlined inactive, filled active on Android). */
export const TAB_MATERIAL_SYMBOLS: Record<TabRouteName, string> = {
  index: 'home',
  browse: 'explore',
  watchlist: 'star',
  trends: 'monitoring',
  settings: 'settings',
};

/** iOS tab bar keeps Ionicons for platform-native chrome. */
export const TAB_IONICONS: Record<TabRouteName, TabIoniconName> = {
  index: 'home',
  browse: 'list',
  watchlist: 'star',
  trends: 'stats-chart',
  settings: 'settings',
};

export function isTabRouteName(name: string): name is TabRouteName {
  return (TAB_ROUTES as readonly string[]).includes(name);
}

export function getTabMaterialSymbol(route: string): string | undefined {
  return isTabRouteName(route) ? TAB_MATERIAL_SYMBOLS[route] : undefined;
}

export function getTabIonicon(route: string): TabIoniconName | undefined {
  return isTabRouteName(route) ? TAB_IONICONS[route] : undefined;
}

export function getTabLabel(route: string, fallback?: string): string {
  if (isTabRouteName(route)) return TAB_LABELS[route];
  return fallback ?? route;
}
