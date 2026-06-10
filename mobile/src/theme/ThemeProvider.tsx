import { useMaterial3Theme } from '@pchmn/expo-material3-theme';
import * as SystemUI from 'expo-system-ui';
import React, { createContext, useContext, useEffect, useMemo } from 'react';
import { useColorScheme } from 'react-native';

import { useStore } from '../data/store';
import { BRAND_SOURCE_COLOR } from './m3Palette';
import { resolveM3Theme, resolveTheme, type Theme } from './theme';

const ThemeContext = createContext<Theme>(resolveTheme('system', 'dark'));

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const system = useColorScheme();
  const mode = useStore((s) => s.prefs.themeMode);
  const { theme: material3 } = useMaterial3Theme({ fallbackSourceColor: BRAND_SOURCE_COLOR });
  const theme = useMemo(
    () => resolveM3Theme(mode, system, material3),
    [material3, mode, system],
  );

  useEffect(() => {
    void SystemUI.setBackgroundColorAsync(theme.colors.bg);
  }, [theme.colors.bg]);

  return <ThemeContext.Provider value={theme}>{children}</ThemeContext.Provider>;
}

export const useTheme = (): Theme => useContext(ThemeContext);
