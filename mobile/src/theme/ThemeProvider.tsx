import React, { createContext, useContext, useMemo } from 'react';
import { useColorScheme } from 'react-native';

import { useStore } from '../data/store';
import { darkTheme, lightTheme, type Theme } from './theme';

const ThemeContext = createContext<Theme>(darkTheme);

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const system = useColorScheme();
  const mode = useStore((s) => s.prefs.themeMode);
  const theme = useMemo<Theme>(() => {
    const resolved = mode === 'system' ? system ?? 'dark' : mode;
    return resolved === 'light' ? lightTheme : darkTheme;
  }, [mode, system]);

  return <ThemeContext.Provider value={theme}>{children}</ThemeContext.Provider>;
}

export const useTheme = (): Theme => useContext(ThemeContext);
