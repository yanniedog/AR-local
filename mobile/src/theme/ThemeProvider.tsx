import * as SystemUI from 'expo-system-ui';
import React, { createContext, useContext, useEffect, useMemo } from 'react';
import { useColorScheme } from 'react-native';

import { useStore } from '../data/store';
import { resolveTheme, type Theme } from './theme';

const ThemeContext = createContext<Theme>(resolveTheme('system', 'dark'));

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const system = useColorScheme();
  const mode = useStore((s) => s.prefs.themeMode);
  const theme = useMemo(() => resolveTheme(mode, system), [mode, system]);

  useEffect(() => {
    void SystemUI.setBackgroundColorAsync(theme.colors.bg);
  }, [theme.colors.bg]);

  return <ThemeContext.Provider value={theme}>{children}</ThemeContext.Provider>;
}

export const useTheme = (): Theme => useContext(ThemeContext);
